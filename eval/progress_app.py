"""Live view of the answer evaluation while it runs (refreshes every 5 seconds).

    streamlit run eval/progress_app.py --server.port 8502
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

OUT_DIR = Path("eval/results/answers")
TOTAL = 40
CONFIGS = {"fast_groq": "⚡ Fast · Groq gpt-oss-120b", "agent_groq": "🧠 Agent · Groq (+ fact-check)",
           "fast_local": "💻 Fast · local Llama 3.2 3B"}

st.set_page_config(page_title="OpsMind eval progress", page_icon="📊", layout="wide")
st.title("📊 OpsMind answer evaluation, live")
st.caption("40 synthetic incident tickets per configuration · own ticket hidden from search · "
           "judge: Qwen 3.8 27B · score 4-5 = correct")


def load(name: str) -> list[dict]:
    path = OUT_DIR / f"{name}.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:  # a line being written right now
            pass
    return rows


@st.fragment(run_every=5)
def live() -> None:
    data = {name: load(name) for name in CONFIGS}

    # ---- progress ----
    cols = st.columns(len(CONFIGS))
    for col, (name, label) in zip(cols, CONFIGS.items()):
        rows = data[name]
        scored = [r for r in rows if r.get("judge_score")]
        with col:
            st.markdown(f"**{label}**")
            st.progress(len(rows) / TOTAL, text=f"{len(rows)} / {TOTAL} questions"
                        + (" ✅" if len(rows) >= TOTAL else " ⏳" if rows else ""))
            if scored:
                correct = sum(r["judge_score"] >= 4 for r in scored) / len(scored)
                c1, c2, c3 = st.columns(3)
                c1.metric("Correct", f"{correct:.0%}")
                c2.metric("Avg score", f"{sum(r['judge_score'] for r in scored) / len(scored):.2f}")
                c3.metric("Median time", f"{sorted(r['total_ms'] for r in rows)[len(rows) // 2] / 1000:.1f} s")

    # ---- score distribution ----
    st.subheader("Judge scores (1 = wrong ... 5 = fully correct)")
    dist = pd.DataFrame({CONFIGS[n]: [sum(1 for r in rows if r.get("judge_score") == s) for s in range(1, 6)]
                         for n, rows in data.items()}, index=[f"score {s}" for s in range(1, 6)])
    st.bar_chart(dist, stack=False, height=280)

    # ---- quality signals ----
    st.subheader("Quality signals so far")
    summary = []
    for name, rows in data.items():
        if not rows:
            continue
        n = len(rows)
        summary.append({
            "configuration": CONFIGS[name], "answers": n,
            "runbook found": f"{sum(r['runbook_retrieved'] for r in rows) / n:.0%}",
            "runbook cited": f"{sum(r['runbook_cited'] for r in rows) / n:.0%}",
            "cited sentences": f"{sum(r['citation_coverage'] for r in rows) / n:.0%}",
            "hallucinated sources": sum(r["invalid_citations"] for r in rows),
        })
    if summary:
        st.dataframe(pd.DataFrame(summary), hide_index=True, use_container_width=True)

    # ---- latest results ----
    st.subheader("Latest answers")
    # Configurations run in order, so the newest answers are at the end of the last started config.
    recent = [r for name in reversed(list(CONFIGS)) for r in reversed(data[name])][:8]
    if recent:
        st.dataframe(pd.DataFrame([{
            "config": CONFIGS[r["config"]], "ticket": r["ticket_id"], "score": r.get("judge_score"),
            "runbook": "cited" if r["runbook_cited"] else "found" if r["runbook_retrieved"] else "missed",
            "time (s)": round(r["total_ms"] / 1000, 1), "judge's reason": r.get("judge_reason", ""),
        } for r in recent]), hide_index=True, use_container_width=True)


live()
