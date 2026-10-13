"""Parse the danluu/post-mortems README: one bullet = one real incident summary."""
import re
from pathlib import Path

from app.ingestion.schema import Document, make_id

# "[Company](https://link). Summary text..."
ENTRY = re.compile(r"^\[(?P<company>[^\]]+)\]\((?P<url>[^)]+)\)\.?\s*(?P<summary>.+)$")
SKIP_SECTIONS = {"Table of Contents", "Other lists of postmortems", "Analysis", "Contributors"}


def load_postmortems(readme: Path) -> list[Document]:
    docs: list[Document] = []
    category = None
    for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("## "):
            category = line[3:].strip()
            continue
        if category is None or category in SKIP_SECTIONS:
            continue
        m = ENTRY.match(line)
        if not m or len(m["summary"]) < 40:
            continue
        docs.append(Document(
            id=make_id("postmortem", m["url"]),
            source_type="postmortem",
            title=f"{m['company']} incident ({category})",
            text=m["summary"].strip(),
            source=m["url"],
            metadata={"company": m["company"], "category": category},
        ))
    return docs
