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
for s in row["sources"]:
    section = f" - {s['section']}" if s["section"] else ""
    with st.expander(f"[{s['number']}] {s['title']}{section}", expanded=False):
        st.text(s["text"])
