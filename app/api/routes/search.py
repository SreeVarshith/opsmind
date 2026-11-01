from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.security import User, get_current_user
from app.rag.retriever import Retriever, get_retriever
from app.rag.vector_store import SearchHit

router = APIRouter(tags=["search"])

SourceType = Literal["runbook", "postmortem", "log", "ticket", "uploaded"]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, examples=["pods keep restarting with CrashLoopBackOff after deploy"])
    top_k: int = Field(5, ge=1, le=50)
    source_types: list[SourceType] | None = Field(None, description="Only search these types")
    service: str | None = Field(None, description="Only tickets for this service, e.g. checkout-api")
    mode: Literal["dense", "sparse", "hybrid"] | None = Field(None, description="Empty = server default (hybrid)")
    rerank: bool | None = Field(None, description="Empty = server default (on)")


class SearchResponse(BaseModel):
    query: str
    mode: str
    reranked: bool
    hits: list[SearchHit]


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest, user: User = Depends(get_current_user),
           retriever: Retriever = Depends(get_retriever)) -> SearchResponse:
    mode = req.mode or retriever.mode
    rerank = (retriever.rerank if req.rerank is None else req.rerank) and retriever.reranker is not None
    hits = retriever.retrieve(req.query, req.top_k, req.source_types, req.service, mode=mode, rerank=rerank,
                              access=user.access)
    return SearchResponse(query=req.query, mode=mode, reranked=rerank, hits=hits)
