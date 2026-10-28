from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agents.incident_agent import AgentResult, IncidentAgent, get_agent
from app.core.query_log import QueryLog, get_query_log
from app.core.security import User, get_current_user
from app.llm.base import LLMError

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequest(BaseModel):
    question: str = Field(..., min_length=3, examples=["etcd cluster reports no leader and kubectl commands time out"])
    service: str | None = None
    provider: Literal["ollama", "openai_compat"] | None = Field(None, description="Empty = default LLM")


@router.post("/ask", response_model=AgentResult)
async def agent_ask(req: AgentRequest, user: User = Depends(get_current_user),
                    agent: IncidentAgent = Depends(get_agent), log: QueryLog = Depends(get_query_log)) -> AgentResult:
    """Careful answer: triage -> search -> draft -> fact-check every sentence -> revise if needed."""
    try:
        r = await agent.run(req.question, req.service, req.provider, access=user.access)
    except LLMError as e:
        log.record(username=user.username, role=user.role, endpoint="agent", question=req.question,
                   error=str(e)[:500])
        raise HTTPException(status_code=503, detail=str(e)) from e
    writer = next((m.split(": ", 1)[1] for m in reversed(r.models_used) if m.startswith(("generate", "revise"))), None)
    log.record(username=user.username, role=user.role, endpoint="agent", question=req.question, model=writer,
               confidence=r.confidence, support_rate=r.support_rate, citation_coverage=r.citation_coverage,
               grounded=int(bool(r.citations) and not r.invalid_citations), n_sources=len(r.sources),
               revisions=r.revisions, total_ms=r.total_ms)
    return r
