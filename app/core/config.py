"""Central configuration. Values come from environment variables or the .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "OpsMind"
    app_version: str = "0.1.0"
    environment: str = "dev"

    # LLM provider: "ollama" (local, free) or "openai_compat" (Groq / OpenRouter / Cerebras, free tiers)
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"

    # Any OpenAI-compatible API. Defaults point at Groq.
    api_base_url: str = "https://api.groq.com/openai/v1"
    api_key: str = ""
    api_model: str = "openai/gpt-oss-120b"
    # For reasoning models (gpt-oss on Groq): low/medium/high. Leave empty for models without it.
    api_reasoning_effort: str = "low"

    # Answering. Sources per type, so one type (e.g. tickets that mention the service name)
    # cannot crowd out the others. Used when the request does not filter by source type.
    answer_quotas: dict[str, int] = {"uploaded": 2, "runbook": 3, "ticket": 2, "postmortem": 1}
    answer_top_k: int = 6              # used instead of quotas when source types are given
    answer_max_tokens: int = 1200

    # Agent (Step 7). The quick steps (analyze, verify) use a smaller model on the API provider;
    # on Groq each model has its own free tokens-per-minute budget, so this doubles the budget.
    agent_fast_model: str = "openai/gpt-oss-20b"
    agent_revise_below: float = 0.7    # rewrite the answer if fewer claims than this are supported
    agent_max_revisions: int = 1

    # Auth (Step 8). Users are created with scripts/create_user.py.
    auth_enabled: bool = True
    jwt_secret: str = ""               # long random string; scripts/create_user.py sets one if empty
    token_ttl_minutes: int = 480       # one working shift
    users_file: str = "config/users.json"

    # Query log for monitoring
    query_log_db: str = "data/opsmind.db"

    # Retrieval
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    sparse_model: str = "Qdrant/bm25"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    retrieval_mode: str = "hybrid"     # "dense", "sparse" or "hybrid"
    # Off by default: the MS MARCO reranker *lowered* MRR 0.614 -> 0.539 on our benchmark
    # (web-search model vs. Kubernetes/log text) and adds ~5 s per query on CPU.
    rerank: bool = False
    rerank_candidates: int = 30        # how many hits the reranker re-scores
    # 127.0.0.1, not localhost: on Windows localhost tries IPv6 first and adds ~2 s to every connection.
    qdrant_url: str = "http://127.0.0.1:6333"
    # If set, Qdrant runs inside Python and stores data in this folder (no Docker needed).
    # Only one process can open it at a time: stop the API before re-indexing.
    qdrant_path: str = ""
    qdrant_collection: str = "opsmind"


@lru_cache
def get_settings() -> Settings:
    return Settings()
