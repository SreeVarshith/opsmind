"""FastAPI entry point. Run with: uvicorn app.main:app --reload"""
from fastapi import FastAPI

from app.api.routes import chat, documents, health
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Agentic RAG copilot for IT incident resolution",
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(documents.router)
