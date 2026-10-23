from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.llm.base import LLMError
from app.rag.answer import Answerer, AskResult, get_answerer

router = APIRouter(tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, examples=[
        "Pods in checkout-api keep restarting and kubectl shows OOMKilled. What should I do?"])
    top_k: int | None = Field(None, ge=1, le=12,
                              description="Empty = balanced mix (3 runbooks, 2 tickets, 1 postmortem)")
    source_types: list[Literal["runbook", "postmortem", "log", "ticket"]] | None = None
    service: str | None = None
    provider: Literal["ollama", "openai_compat"] | None = Field(None, description="Empty = default LLM")


@router.post("/ask", response_model=AskResult)
async def ask(req: AskRequest, answerer: Answerer = Depends(get_answerer)) -> AskResult:
    try:
        return await answerer.ask(req.question, req.top_k, req.source_types, req.service, req.provider)
    except LLMError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
