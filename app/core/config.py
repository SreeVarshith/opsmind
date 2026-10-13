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
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"

    # Any OpenAI-compatible API. Defaults point at Groq.
    api_base_url: str = "https://api.groq.com/openai/v1"
    api_key: str = ""
    api_model: str = "openai/gpt-oss-120b"

    # Retrieval
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    sparse_model: str = "Qdrant/bm25"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    retrieval_mode: str = "hybrid"     # "dense", "sparse" or "hybrid"
    # Off by default: the MS MARCO reranker *lowered* MRR 0.614 -> 0.539 on our benchmark
    # (web-search model vs. Kubernetes/log text) and adds ~5 s per query on CPU.
    rerank: bool = False
    rerank_candidates: int = 30        # how many hits the reranker re-scores
    qdrant_url: str = "http://localhost:6333"
    # If set, Qdrant runs inside Python and stores data in this folder (no Docker needed).
    # Only one process can open it at a time: stop the API before re-indexing.
    qdrant_path: str = ""
    qdrant_collection: str = "opsmind"


@lru_cache
def get_settings() -> Settings:
    return Settings()
