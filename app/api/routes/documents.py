from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core.security import User, get_current_user
from app.ingestion import uploads
from app.ingestion.pipeline import OUTPUT, read_jsonl
from app.ingestion.schema import Document
from app.rag.chunking import chunk_document
from app.rag.vector_store import VectorStore, get_vector_store

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


class UploadedDocument(BaseModel):
    id: str
    filename: str
    uploaded_by: str
    uploaded_at: float
    access: str
    characters: int


def _summary(doc: Document) -> UploadedDocument:
    m = doc.metadata
    return UploadedDocument(id=doc.id, filename=m["filename"], uploaded_by=m["uploaded_by"],
                            uploaded_at=m["uploaded_at"], access=m["access"], characters=len(doc.text))


@router.get("/uploads", response_model=list[UploadedDocument])
def list_uploads() -> list[UploadedDocument]:
    return [_summary(d) for d in uploads.load_all()]


@router.post("/uploads", response_model=UploadedDocument, status_code=status.HTTP_201_CREATED)
def upload_document(file: UploadFile = File(...), access: Literal["public", "restricted"] = Form("public"),
                    user: User = Depends(get_current_user),
                    store: VectorStore = Depends(get_vector_store)) -> UploadedDocument:
    """Add a PDF, Markdown or text file to the knowledge base. It is searchable right away."""
    filename = uploads.clean_filename(file.filename or "")
    data = file.file.read(uploads.MAX_BYTES + 1)
    try:
        text = uploads.extract_text(filename, data)
    except uploads.UploadError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    doc = uploads.make_document(filename, text, user.username, access)
    store.delete_document(doc.id)  # same file name: replace the old version
    store.upsert(chunk_document(doc))
    uploads.save(doc)
    return _summary(doc)


@router.delete("/uploads/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_upload(doc_id: str, store: VectorStore = Depends(get_vector_store)) -> None:
    if not uploads.remove(doc_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    store.delete_document(doc_id)
