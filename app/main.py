"""FastAPI entry point. Run with: uvicorn app.main:app --reload"""
from fastapi import Depends, FastAPI

from app.api.routes import agent, ask, auth, chat, documents, health, metrics, search
from app.core.config import get_settings
from app.core.security import get_current_user, require_role

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Agentic RAG copilot for IT incident resolution",
)

# Public
app.include_router(health.router)
app.include_router(auth.router)
# Any logged-in user (search/ask/agent also filter documents by the user's access level)
app.include_router(chat.router, dependencies=[Depends(get_current_user)])
app.include_router(search.router)
app.include_router(ask.router)
app.include_router(agent.router)
# Raw documents bypass search filtering, so only roles that may see everything get them
app.include_router(documents.router, dependencies=[Depends(require_role("admin", "sre"))])
app.include_router(metrics.router)
