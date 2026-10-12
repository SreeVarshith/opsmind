"""Central configuration. Values come from environment variables or the .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "OpsMind"
    app_version: str = "0.1.0"
    environment: str = "dev"

    # LLM provider: "ollama" (local) or "anthropic" (API)
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"

    # Retrieval
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "opsmind"


@lru_cache
def get_settings() -> Settings:
    return Settings()
