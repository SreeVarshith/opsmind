"""Shared types for every LLM provider."""
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMResponse(BaseModel):
    text: str
    provider: str
    model: str
    latency_ms: int


class LLMError(Exception):
    """Raised when a provider cannot answer (not running, bad key, rate limited...)."""


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def generate(self, messages: list[Message], temperature: float = 0.2, max_tokens: int = 1024) -> LLMResponse:
        """Send a chat conversation to the model and return its reply."""
