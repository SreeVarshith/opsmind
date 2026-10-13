"""Parse Prometheus Operator runbooks (Markdown with YAML front matter)."""
import re
from pathlib import Path

from app.ingestion.schema import Document, make_id

RUNBOOK_URL = "https://runbooks.prometheus-operator.dev/runbooks/{component}/{alert}/"
FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_runbook(path: Path) -> Document | None:
    raw = path.read_text(encoding="utf-8", errors="replace")

    title = None
    if m := FRONT_MATTER.match(raw):
        for line in m.group(1).splitlines():
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip("\"'")
        raw = raw[m.end():]

    body = raw.strip()
    if len(body) < 50:  # empty or placeholder file
        return None

    component, _, alert = path.stem.partition("__")  # file name is component__AlertName.md
    sections = re.findall(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    return Document(
        id=make_id("runbook", component, alert),
        source_type="runbook",
        title=f"{alert} ({component})" if not title else f"{title} [{alert}]",
        text=body,
        source=RUNBOOK_URL.format(component=component, alert=alert.lower()),
        metadata={"component": component, "alert": alert, "sections": sections},
    )


def load_runbooks(folder: Path) -> list[Document]:
    docs = [parse_runbook(p) for p in sorted(folder.glob("*.md"))]
    return [d for d in docs if d is not None]
