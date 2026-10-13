from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.ingestion.text import normalize_text
from app.rag.vector_store import SearchHit, VectorStore, get_vector_store

router = APIRouter(tags=["search"])

SourceType = Literal["runbook", "postmortem", "log", "ticket"]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, examples=["pods keep restarting with CrashLoopBackOff after deploy"])
    top_k: int = Field(5, ge=1, le=50)
    source_types: list[SourceType] | None = Field(None, description="Only search these types")
    service: str | None = Field(None, description="Only tickets for this service, e.g. checkout-api")


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest, store: VectorStore = Depends(get_vector_store)) -> SearchResponse:
    query = normalize_text(req.query)
    return SearchResponse(query=query, hits=store.search(query, req.top_k, req.source_types, req.service))
