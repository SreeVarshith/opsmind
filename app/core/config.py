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
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "opsmind"


@lru_cache
def get_settings() -> Settings:
    return Settings()
