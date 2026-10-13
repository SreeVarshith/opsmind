"""Run every parser and write one combined file: data/processed/documents.jsonl

    python -m app.ingestion.pipeline
"""
from collections import Counter
from pathlib import Path

from app.ingestion.logs import load_logs
from app.ingestion.postmortems import load_postmortems
from app.ingestion.runbooks import load_runbooks
from app.ingestion.schema import Document
from app.ingestion.text import normalize_text
from app.ingestion.tickets import load_tickets

RAW = Path("data/raw")
OUTPUT = Path("data/processed/documents.jsonl")


def collect(raw: Path = RAW) -> list[Document]:
    docs = (
        load_runbooks(raw / "runbooks")
        + load_postmortems(raw / "postmortems" / "README.md")
        + load_logs(raw / "logs")
        + load_tickets(raw / "tickets" / "tickets.jsonl")
    )
    for d in docs:
        d.title, d.text = normalize_text(d.title), normalize_text(d.text)
    unique = {d.id: d for d in docs}  # drop duplicates by stable id
    return list(unique.values())


def write_jsonl(docs: list[Document], path: Path = OUTPUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(d.model_dump_json() + "\n")


def read_jsonl(path: Path = OUTPUT) -> list[Document]:
    with path.open(encoding="utf-8") as f:
        return [Document.model_validate_json(line) for line in f if line.strip()]


if __name__ == "__main__":
    docs = collect()
    write_jsonl(docs)
    counts = Counter(d.source_type for d in docs)
    chars = sum(len(d.text) for d in docs)
    print(f"Wrote {len(docs)} documents ({chars / 1000:.0f}K characters) to {OUTPUT}")
    for source_type, n in counts.most_common():
        print(f"  {source_type:<11} {n}")
