from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agents.incident_agent import AgentResult, IncidentAgent, get_agent
from app.llm.base import LLMError

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequest(BaseModel):
    question: str = Field(..., min_length=3, examples=["etcd cluster reports no leader and kubectl commands time out"])
    service: str | None = None
    provider: Literal["ollama", "openai_compat"] | None = Field(None, description="Empty = default LLM")


@router.post("/ask", response_model=AgentResult)
async def agent_ask(req: AgentRequest, agent: IncidentAgent = Depends(get_agent)) -> AgentResult:
    """Careful answer: triage -> search -> draft -> fact-check every sentence -> revise if needed."""
    try:
        return await agent.run(req.question, req.service, req.provider)
    except LLMError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
