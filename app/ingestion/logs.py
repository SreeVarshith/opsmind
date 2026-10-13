"""Turn Loghub log samples into one document per (system, event template).

Raw log lines are too repetitive to index one by one (2,000 lines -> a few dozen distinct
events). Grouping by template keeps one searchable document per kind of event, with how
often it occurred, its severity levels and a few real example lines.
"""
import csv
from collections import Counter, defaultdict
from pathlib import Path

from app.ingestion.schema import Document, make_id

MAX_EXAMPLES = 3


def load_log_file(path: Path) -> list[Document]:
    system = path.stem
    groups: dict[str, list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.DictReader(f):
            groups[row["EventTemplate"]].append(row)

    total = sum(len(rows) for rows in groups.values())
    docs = []
    for template, rows in groups.items():
        levels = Counter(r.get("Level") or "N/A" for r in rows)
        components = Counter(r.get("Component") or "N/A" for r in rows)
        examples = list(dict.fromkeys(r["Content"] for r in rows))[:MAX_EXAMPLES]  # distinct, in order
        level_str = ", ".join(f"{lvl}: {n}" for lvl, n in levels.most_common())
        top_components = [c for c, _ in components.most_common(3) if c != "N/A"]

        text = (
            f"System: {system}\n"
            f"Log event template: {template}\n"
            f"Occurrences: {len(rows)} of {total} sampled lines\n"
            f"Severity levels: {level_str}\n"
            + (f"Main components: {', '.join(top_components)}\n" if top_components else "")
            + "Example lines:\n" + "\n".join(f"  {e}" for e in examples)
        )
        event_id = rows[0].get("EventId", "")
        docs.append(Document(
            id=make_id("log", system, template),
            source_type="log",
            title=f"{system} log event {event_id}: {template[:80]}",
            text=text,
            source=f"loghub/{system}#{event_id}",
            metadata={"system": system, "event_id": event_id, "count": len(rows),
                      "levels": dict(levels), "template": template},
        ))
    return docs


def load_logs(folder: Path) -> list[Document]:
    return [doc for p in sorted(folder.glob("*.csv")) for doc in load_log_file(p)]
