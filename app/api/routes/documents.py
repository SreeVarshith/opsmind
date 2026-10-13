from collections import Counter

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ingestion.pipeline import OUTPUT, read_jsonl
from app.ingestion.schema import Document

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentStats(BaseModel):
    total: int
    by_source_type: dict[str, int]
    total_characters: int


def _load() -> list[Document]:
    if not OUTPUT.exists():
        raise HTTPException(404, "No documents yet. Run: python -m app.ingestion.pipeline")
    return read_jsonl(OUTPUT)


@router.get("/stats", response_model=DocumentStats)
def stats() -> DocumentStats:
    docs = _load()
    return DocumentStats(
        total=len(docs),
        by_source_type=dict(Counter(d.source_type for d in docs)),
        total_characters=sum(len(d.text) for d in docs),
    )


@router.get("/sample", response_model=list[Document])
def sample(source_type: str | None = None, limit: int = 3) -> list[Document]:
    docs = [d for d in _load() if source_type is None or d.source_type == source_type]
    return docs[: min(limit, 20)]
