from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.llm.base import LLMError, LLMResponse, Message
from app.llm.router import LLMRouter, get_router

router = APIRouter(tags=["chat"])

SYSTEM_PROMPT = (
    "You are OpsMind, an assistant for IT operations engineers. "
    "Answer concisely and practically. If you are not sure, say so."
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, examples=["What does 'OOMKilled' mean in Kubernetes?"])
    provider: Literal["ollama", "openai_compat"] | None = Field(None, description="Leave empty to use the default")
    fallback: bool = True


@router.post("/chat", response_model=LLMResponse)
async def chat(req: ChatRequest, llm: LLMRouter = Depends(get_router)) -> LLMResponse:
    messages = [Message(role="system", content=SYSTEM_PROMPT), Message(role="user", content=req.message)]
    try:
        return await llm.generate(messages, provider=req.provider, fallback=req.fallback)
    except LLMError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
