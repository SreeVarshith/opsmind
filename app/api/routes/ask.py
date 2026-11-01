from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.query_log import QueryLog, get_query_log
from app.core.security import User, get_current_user
from app.llm.base import LLMError
from app.rag.answer import Answerer, AskResult, get_answerer

router = APIRouter(tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, examples=[
        "Pods in checkout-api keep restarting and kubectl shows OOMKilled. What should I do?"])
    top_k: int | None = Field(None, ge=1, le=12,
                              description="Empty = balanced mix (3 runbooks, 2 tickets, 1 postmortem)")
    source_types: list[Literal["runbook", "postmortem", "log", "ticket", "uploaded"]] | None = None
    service: str | None = None
    provider: Literal["ollama", "openai_compat"] | None = Field(None, description="Empty = default LLM")


@router.post("/ask", response_model=AskResult)
async def ask(req: AskRequest, user: User = Depends(get_current_user), answerer: Answerer = Depends(get_answerer),
              log: QueryLog = Depends(get_query_log)) -> AskResult:
    """Fast answer: one LLM call over the retrieved sources, with citation checks."""
    try:
        r = await answerer.ask(req.question, req.top_k, req.source_types, req.service, req.provider,
                               access=user.access)
    except LLMError as e:
        log.record(username=user.username, role=user.role, endpoint="ask", question=req.question, error=str(e)[:500])
        raise HTTPException(status_code=503, detail=str(e)) from e
    log.record(username=user.username, role=user.role, endpoint="ask", question=req.question, provider=r.provider,
               model=r.model, citation_coverage=r.citation_coverage, grounded=int(r.grounded),
               n_sources=len(r.sources), total_ms=r.timings.total_ms)
    return r
