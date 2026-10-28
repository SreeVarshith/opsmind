"""OpsMind web UI. It only talks to the FastAPI backend over HTTP, like any other client.

    streamlit run ui/streamlit_app.py
"""
import os

import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("OPSMIND_API_URL", "http://localhost:8000")
VERDICT_ICON = {"supported": "✅", "partial": "⚠️", "unsupported": "❌"}
CONFIDENCE_STYLE = {
    "high": (st.success, "High confidence: most statements were verified against the sources."),
    "medium": (st.warning, "Medium confidence: some statements could not be verified. Check the flagged ones."),
    "low": (st.error, "Low confidence: most of this answer is not backed by the knowledge base."),
    "unverified": (st.info, "Not verified: the fact-checker was unavailable for this answer."),
    "none": (st.info, "No relevant documents found."),
}

st.set_page_config(page_title="OpsMind", page_icon="🛠️", layout="wide")


# ---------- API helpers ----------
def api(method: str, path: str, **kwargs) -> httpx.Response:
    headers = {"Authorization": f"Bearer {st.session_state['token']}"} if "token" in st.session_state else {}
    return httpx.request(method, API_URL + path, headers=headers, timeout=300, **kwargs)


def logout(message: str | None = None) -> None:
    for key in ("token", "user", "history"):
        st.session_state.pop(key, None)
    if message:
        st.session_state["flash"] = message


def call(method: str, path: str, **kwargs) -> dict | None:
    try:
        r = api(method, path, **kwargs)
    except httpx.HTTPError:
        st.error(f"Cannot reach the OpsMind API at {API_URL}. Is it running?")
        return None
    if r.status_code == 401:
        logout("Your session expired. Please log in again.")
        st.rerun()
    if r.status_code != 200:
        st.error(f"Error {r.status_code}: {r.json().get('detail', r.text) if r.content else ''}")
        return None
    return r.json()


# ---------- login ----------
def login_form() -> None:
    st.title("🛠️ OpsMind")
    st.caption("Incident-resolution copilot: answers from your runbooks, tickets and postmortems, with sources.")
    if msg := st.session_state.pop("flash", None):
        st.info(msg)
    with st.form("login", clear_on_submit=False):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Log in", type="primary"):
            try:
                r = httpx.post(API_URL + "/auth/login", json={"username": username, "password": password}, timeout=30)
            except httpx.HTTPError:
                st.error(f"Cannot reach the OpsMind API at {API_URL}. Is it running?")
                return
            if r.status_code == 200:
                body = r.json()
                st.session_state["token"] = body["access_token"]
                st.session_state["user"] = {"username": body["username"], "role": body["role"]}
                st.rerun()
            else:
                st.error("Wrong username or password.")


# ---------- ask page ----------
def render_result(res: dict, mode: str) -> None:
    if mode == "agent":
        show, text = CONFIDENCE_STYLE.get(res["confidence"], (st.info, res["confidence"]))
        show(text)
    st.markdown(res["answer"])

    cols = st.columns(4)
    if mode == "agent":
        cols[0].metric("Verified statements", f"{res['support_rate']:.0%}" if res["support_rate"] is not None else "n/a")
        cols[1].metric("Cited statements", f"{res['citation_coverage']:.0%}")
        cols[2].metric("Revisions", res["revisions"])
        cols[3].metric("Time", f"{res['total_ms'] / 1000:.1f} s")
    else:
        cols[0].metric("Grounded", "yes" if res["grounded"] else "no")
        cols[1].metric("Cited statements", f"{res['citation_coverage']:.0%}")
        cols[2].metric("Model", (res.get("model") or "n/a").split("/")[-1])
        cols[3].metric("Time", f"{res['timings']['total_ms'] / 1000:.1f} s")

    cited = {c["number"] for c in res["citations"]}
    with st.expander(f"📚 Sources ({len(res['sources'])}, {len(cited)} cited)"):
        for s in res["sources"]:
            mark = "**cited**" if s["number"] in cited else "not cited"
            section = f" · {s['section']}" if s["section"] else ""
            link = f"[{s['title']}]({s['source']})" if s["source"].startswith("http") else s["title"]
            st.markdown(f"**[{s['number']}]** `{s['source_type']}` {link}{section} · {mark}")
            st.caption(s["snippet"][:240] + ("..." if len(s["snippet"]) > 240 else ""))

    if mode == "agent" and res["claims"]:
        with st.expander("🔎 Fact check, sentence by sentence"):
            st.dataframe(pd.DataFrame([{"": VERDICT_ICON[c["verdict"]], "verdict": c["verdict"],
                                        "statement": c["text"], "sources": ", ".join(map(str, c["sources"]))}
                                       for c in res["claims"]]), hide_index=True, use_container_width=True)
    if mode == "agent":
        with st.expander("🧭 How the agent worked"):
            if res["analysis"]:
                st.markdown(f"**Triage:** `{res['analysis'].get('category')}` - {res['analysis'].get('summary')}")
                st.markdown(f"**Search query:** {res['search_query']}")
            st.dataframe(pd.DataFrame(res["trace"]), hide_index=True, use_container_width=True)
            st.caption("Models: " + " · ".join(res["models_used"]))


def ask_page() -> None:
    st.title("Ask OpsMind")
    with st.sidebar:
        st.subheader("Settings")
        mode = st.radio("Mode", ["agent", "ask"], format_func=lambda m: {
            "agent": "🧠 Careful (fact-checked)", "ask": "⚡ Fast (one step)"}[m])
        provider = st.radio("Model", ["openai_compat", "ollama"], format_func=lambda p: {
            "openai_compat": "☁️ Groq (best quality)", "ollama": "💻 Local Llama 3B (offline)"}[p])
        service = st.text_input("Service (optional)", placeholder="e.g. checkout-api")

    st.session_state.setdefault("history", [])
    for item in st.session_state["history"]:
        with st.chat_message("user"):
            st.markdown(item["question"])
        with st.chat_message("assistant", avatar="🛠️"):
            render_result(item["result"], item["mode"])

    if question := st.chat_input("Describe the incident or paste the error message..."):
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant", avatar="🛠️"):
            label = "Triage, search, draft, fact-check..." if mode == "agent" else "Searching and answering..."
            with st.spinner(label):
                body = {"question": question, "provider": provider, "service": service or None}
                res = call("POST", "/agent/ask" if mode == "agent" else "/ask", json=body)
            if res:
                render_result(res, mode)
                st.session_state["history"].append({"question": question, "result": res, "mode": mode})


# ---------- monitoring page ----------
def monitoring_page() -> None:
    st.title("Monitoring")
    hours = st.select_slider("Time window", options=[1, 24, 24 * 7, 24 * 30], value=24 * 7,
                             format_func=lambda h: {1: "1 hour", 24: "24 hours", 168: "7 days", 720: "30 days"}[h])
    data = call("GET", "/metrics/summary", params={"hours": hours, "recent": 50})
    if not data:
        return
    c = st.columns(5)
    c[0].metric("Questions", data["total_queries"])
    c[1].metric("Errors", data["errors"])
    c[2].metric("Median time", f"{data['latency_ms']['p50'] / 1000:.1f} s" if data["latency_ms"]["p50"] else "n/a")
    c[3].metric("95th pct time", f"{data['latency_ms']['p95'] / 1000:.1f} s" if data["latency_ms"]["p95"] else "n/a")
    c[4].metric("Avg verified", f"{data['mean_support_rate']:.0%}" if data["mean_support_rate"] is not None else "n/a")

    left, right = st.columns(2)
    for col, key, title in ((left, "by_confidence", "Answers by confidence"), (right, "by_endpoint", "Questions by mode")):
        with col:
            st.subheader(title)
            if data[key]:
                st.bar_chart(pd.Series(data[key], name="questions"))
    st.subheader("Recent questions")
    if data["recent"]:
        df = pd.DataFrame(data["recent"])
        df["time"] = pd.to_datetime(df["ts"], unit="s").dt.tz_localize("UTC").dt.tz_convert(None)
        st.dataframe(df[["time", "username", "endpoint", "question", "model", "confidence", "support_rate",
                         "citation_coverage", "total_ms", "error"]], hide_index=True, use_container_width=True)


# ---------- main ----------
if "token" not in st.session_state:
    login_form()
else:
    user = st.session_state["user"]
    with st.sidebar:
        st.markdown(f"### 🛠️ OpsMind\nSigned in as **{user['username']}** · `{user['role']}`")
        pages = ["Ask"] + (["Monitoring"] if user["role"] in ("admin", "sre") else [])
        page = st.radio("Page", pages, label_visibility="collapsed")
        if st.button("Log out"):
            logout()
            st.rerun()
        st.divider()
    # A plain if/else on purpose: Streamlit "magic" would display the None of a bare expression.
    if page == "Ask":
        ask_page()
    else:
        monitoring_page()
