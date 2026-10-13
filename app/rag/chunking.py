"""Split documents into chunks that are small enough to embed and precise enough to cite.

Strategy per source type:
  - runbook: one chunk per "## Section" (Meaning / Impact / Diagnosis / Mitigation), so an
    answer can cite exactly the Mitigation section instead of the whole page
  - postmortem, ticket, log: already short, kept whole
  - anything longer than MAX_CHARS is split on paragraph boundaries with a small overlap

Every chunk starts with a context header (document title + section). Without it, a chunk
that only says "Restart the pod" would lose the information of which alert it belongs to.
"""
import re

from pydantic import BaseModel

from app.ingestion.schema import Document

MAX_CHARS = 1200       # bge-small reads at most 512 tokens (~2000 chars); stay well below
OVERLAP_CHARS = 150


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    source_type: str
    title: str
    section: str | None
    text: str           # what gets embedded and shown to the LLM (includes the context header)
    source: str
    metadata: dict


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    parts, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        if current and len(current) + len(para) + 2 > MAX_CHARS:
            parts.append(current.strip())
            current = current[-OVERLAP_CHARS:] + "\n\n"  # carry a little context forward
        current += para + "\n\n"
    if current.strip():
        parts.append(current.strip())
    # a single paragraph can still be too long: hard-split it
    return [p[i:i + MAX_CHARS] for p in parts for i in range(0, len(p), MAX_CHARS - OVERLAP_CHARS)]


def _runbook_sections(doc: Document) -> list[tuple[str | None, str]]:
    pieces = re.split(r"^##\s+(.+)$", doc.text, flags=re.MULTILINE)
    # pieces = [intro, heading1, body1, heading2, body2, ...]
    sections = []
    intro = re.sub(r"^#\s+.*$", "", pieces[0], flags=re.MULTILINE).strip()
    if intro:
        sections.append((None, intro))
    for heading, body in zip(pieces[1::2], pieces[2::2]):
        if body.strip():
            sections.append((heading.strip(), body.strip()))
    return sections or [(None, doc.text)]


def chunk_document(doc: Document) -> list[Chunk]:
    sections = _runbook_sections(doc) if doc.source_type == "runbook" else [(None, doc.text)]
    chunks = []
    for section, body in sections:
        for part in _split_long(body):
            header = f"[{doc.source_type}] {doc.title}" + (f" - {section}" if section else "")
            n = len(chunks)
            chunks.append(Chunk(
                chunk_id=f"{doc.id}#{n}",
                doc_id=doc.id,
                source_type=doc.source_type,
                title=doc.title,
                section=section,
                text=f"{header}\n{part}",
                source=doc.source,
                metadata=doc.metadata,
            ))
    return chunks


def chunk_documents(docs: list[Document]) -> list[Chunk]:
    return [c for d in docs for c in chunk_document(d)]
