"""Conversations: a live streamed answer, saved history, follow-up questions and feedback.

POST /conversations/stream answers with Server-Sent Events, so the UI can show each agent step and
the answer as it is written. Event types: step, sources, token, result, saved, error.
"""
import json
import logging
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.incident_agent import IncidentAgent, get_agent
from app.core.conversations import ConversationStore, get_conversation_store
from app.core.query_log import QueryLog, get_query_log
from app.core.security import User, get_current_user
from app.llm.base import LLMError
from app.rag.answer import Answerer, get_answerer

router = APIRouter(prefix="/conversations", tags=["conversations"])
logger = logging.getLogger(__name__)


class StreamRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=8000)
    conversation_id: str | None = None
    mode: Literal["agent", "fast"] = "agent"
    provider: Literal["ollama", "openai_compat"] | None = None
    service: str | None = None


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"] | None = None
    fixed: bool | None = None


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _log_result(log: QueryLog, user: User, req: StreamRequest, r: dict) -> None:
    common = {"username": user.username, "role": user.role, "question": req.question,
              "citation_coverage": r["citation_coverage"], "n_sources": len(r["sources"])}
    if req.mode == "agent":
        writer = next((m.split(": ", 1)[1] for m in reversed(r["models_used"]) if m.startswith(("generate", "revise"))),
                      None)
        log.record(**common, endpoint="agent", model=writer, confidence=r["confidence"],
                   support_rate=r["support_rate"], revisions=r["revisions"], total_ms=r["total_ms"],
                   grounded=int(bool(r["citations"]) and not r["invalid_citations"]))
    else:
        log.record(**common, endpoint="ask", provider=r["provider"], model=r["model"], grounded=int(r["grounded"]),
                   total_ms=r["timings"]["total_ms"])


@router.post("/stream")
async def stream_answer(req: StreamRequest, user: User = Depends(get_current_user),
                        answerer: Answerer = Depends(get_answerer), agent: IncidentAgent = Depends(get_agent),
                        store: ConversationStore = Depends(get_conversation_store),
                        log: QueryLog = Depends(get_query_log)) -> StreamingResponse:
    history = None
    if req.conversation_id:
        history = store.history(user.username, req.conversation_id)
        if history is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    async def events() -> AsyncIterator[str]:
        try:
            if req.mode == "agent":
                source = agent.run_stream(req.question, req.service, req.provider, user.access, history)
            else:
                source = answerer.ask_stream(req.question, req.service, req.provider, user.access, history)
            async for event in source:
                yield sse(event)
                if event["type"] == "result":
                    r = event["result"]
                    conversation_id, message_id = store.save_exchange(
                        user.username, req.conversation_id, req.question, r["answer"], req.mode, r)
                    _log_result(log, user, req, r)
                    yield sse({"type": "saved", "conversation_id": conversation_id, "message_id": message_id})
        except LLMError as e:
            log.record(username=user.username, role=user.role, endpoint=req.mode, question=req.question,
                       error=str(e)[:500])
            yield sse({"type": "error", "detail": "The AI model is unavailable or at its rate limit. Try again in a minute."})
        except Exception:  # the HTTP status is already sent, so the error must travel as an event
            logger.exception("streamed answer failed")
            log.record(username=user.username, role=user.role, endpoint=req.mode, question=req.question,
                       error="internal error")
            yield sse({"type": "error", "detail": "Something went wrong while answering. Try again."})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("")
def list_conversations(user: User = Depends(get_current_user),
                       store: ConversationStore = Depends(get_conversation_store)) -> list[dict]:
    return store.list_for_user(user.username)


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, user: User = Depends(get_current_user),
                     store: ConversationStore = Depends(get_conversation_store)) -> dict:
    conversation = store.get(user.username, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, user: User = Depends(get_current_user),
                        store: ConversationStore = Depends(get_conversation_store)) -> None:
    if not store.delete(user.username, conversation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")


@router.put("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def set_feedback(message_id: str, req: FeedbackRequest, user: User = Depends(get_current_user),
                 store: ConversationStore = Depends(get_conversation_store)) -> None:
    if not store.set_feedback(user.username, message_id, req.rating, req.fixed):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Answer not found")
