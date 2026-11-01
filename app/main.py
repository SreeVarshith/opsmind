"""FastAPI entry point. Run with: uvicorn app.main:app --reload"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app.api.routes import agent, ask, auth, chat, conversations, documents, health, metrics, search
from app.core.config import get_settings
from app.core.security import get_current_user, require_role
from app.rag.vector_store import get_vector_store

settings = get_settings()
logger = logging.getLogger(__name__)


async def warm_up() -> None:
    try:
        await asyncio.to_thread(get_vector_store)
    except Exception:
        logger.exception("could not load the search models at startup; the first question will retry")


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(warm_up())  # in the background, so the server can start answering health checks
    yield
    task.cancel()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Agentic RAG copilot for IT incident resolution",
    lifespan=lifespan,
)

# Public
app.include_router(health.router)
app.include_router(auth.router)
# Any logged-in user (search/ask/agent also filter documents by the user's access level)
app.include_router(chat.router, dependencies=[Depends(get_current_user)])
app.include_router(search.router)
app.include_router(ask.router)
app.include_router(agent.router)
app.include_router(conversations.router)
# Raw documents bypass search filtering, so only roles that may see everything get them
app.include_router(documents.router, dependencies=[Depends(require_role("admin", "sre"))])
app.include_router(metrics.router)

# The React app (frontend/dist, built by `npm run build`), served by the same process.
FRONTEND = Path("frontend/dist").resolve()


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/app/")


@app.get("/app/{path:path}", include_in_schema=False)
def frontend(path: str) -> FileResponse:
    """Serve built files; any other path gets index.html, because React handles its own routes."""
    index = FRONTEND / "index.html"
    if not index.exists():
        raise HTTPException(404, "Frontend not built. Run: cd frontend && npm ci && npm run build")
    file = (FRONTEND / path).resolve()
    if file.is_file() and file.is_relative_to(FRONTEND):  # never serve files outside the build folder
        return FileResponse(file)
    return FileResponse(index)
