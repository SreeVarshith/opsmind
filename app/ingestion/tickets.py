"""Load IT support tickets from a JSONL file (one ticket per line)."""
import json
from pathlib import Path

from app.ingestion.schema import Document, make_id


def ticket_to_document(t: dict) -> Document:
    text = (
        f"Ticket {t['ticket_id']} | Service: {t['service']} | Priority: {t['priority']}\n"
        f"Problem: {t['title']}\n"
        f"Description: {t['description']}\n"
        f"Root cause: {t['root_cause']}\n"
        f"Resolution: {t['resolution']}"
    )
    return Document(
        id=make_id("ticket", t["ticket_id"]),
        source_type="ticket",
        title=f"{t['ticket_id']}: {t['title']}",
        text=text,
        source=f"tickets/{t['ticket_id']}",
        metadata={k: t[k] for k in ("ticket_id", "service", "priority", "related_runbook") if k in t},
    )


def load_tickets(path: Path) -> list[Document]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [ticket_to_document(json.loads(line)) for line in f if line.strip()]
