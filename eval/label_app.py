"""Blind labelling tool for the fact-checker audit.

    streamlit run eval/label_app.py

Shows one claim at a time with the full sources the agent had. You decide whether the sources
support it. The fact-checker's own verdict is never shown. Labels are saved after every click.
"""
import json
from pathlib import Path

import streamlit as st

SAMPLE = Path("eval/labels/verifier_sample.jsonl")
CHOICES = {"supported": "✅ Supported", "partial": "⚠️ Partly supported", "unsupported": "❌ Not supported"}

st.set_page_config(page_title="OpsMind labelling", page_icon="🏷️", layout="wide")

if not SAMPLE.exists():
    st.error("No sample yet. Run: python -m eval.verifier_audit sample")
    st.stop()

rows = [json.loads(line) for line in SAMPLE.open(encoding="utf-8")]


def save() -> None:
    SAMPLE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


todo = [i for i, r in enumerate(rows) if r["human_label"] is None]
done = len(rows) - len(todo)
st.progress(done / len(rows), text=f"{done} of {len(rows)} labelled")

if not todo:
    st.success("All claims labelled. Now run: python -m eval.verifier_audit score")
    if st.button("Undo last label"):
        rows[-1]["human_label"] = None
        save()
        st.rerun()
    st.stop()

i = st.session_state.get("current", todo[0])
if rows[i]["human_label"] is not None:
    i = todo[0]
row = rows[i]

st.markdown("#### Does the source material support this statement?")
st.info(row["claim"])
st.caption("Judge only from the sources below, not from your own knowledge. "
           "**Partly** = some detail (a number, a command, a cause) is not in any source.")

cols = st.columns(len(CHOICES))
for col, (value, label) in zip(cols, CHOICES.items()):
    if col.button(label, use_container_width=True, key=f"{value}-{i}"):
        rows[i]["human_label"] = value
        save()
        st.session_state.pop("current", None)
        st.rerun()

st.markdown("---")
st.markdown("### 📚 Sources the assistant had")
st.caption("Type a key word or number from the statement (e.g. `500m`, `memory`, `restart`) to highlight it "
           "in every source below.")
term = st.text_input("🔍 Find a word in the sources", key=f"find-{i}", placeholder="e.g. 500m").strip()


def highlight(text: str, word: str) -> tuple[str, int]:
    """Escape the text for display and mark every case-insensitive match of `word`."""
    import html
    import re

    safe = html.escape(text)
    if not word:
        return safe, 0
    pattern = re.compile(re.escape(html.escape(word)), re.IGNORECASE)
    return pattern.subn(lambda m: f"<mark style='background:#ffd54f;color:#000'>{m.group(0)}</mark>", safe)


for s in row["sources"]:
    section = f" - {s['section']}" if s["section"] else ""
    shown, hits = highlight(s["text"], term)
    found = f"  ·  **{hits} match{'es' if hits != 1 else ''}**" if term else ""
    with st.expander(f"[{s['number']}] {s['title']}{section}{found}", expanded=True):
        st.markdown(f"<div style='white-space:pre-wrap;font-size:0.9rem'>{shown}</div>", unsafe_allow_html=True)
