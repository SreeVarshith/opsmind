"""Local models served by Ollama (runs on your own GPU, free, offline)."""
import json
import time
from collections.abc import AsyncIterator

import httpx

from app.llm.base import LLMError, LLMProvider, LLMResponse, Message


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._transport = transport  # lets tests inject a fake server

    async def generate(self, messages: list[Message], temperature: float = 0.2, max_tokens: int = 1024,
                       model: str | None = None) -> LLMResponse:
        model = model or self.model
        payload = {
            "model": model,
            "messages": [m.model_dump() for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=120, transport=self._transport) as client:
                r = await client.post("/api/chat", json=payload)
                r.raise_for_status()
        except httpx.ConnectError as e:
            raise LLMError("Ollama is not running. Start the Ollama app or run `ollama serve`.") from e
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Ollama error {e.response.status_code}: {e.response.text}") from e
        except httpx.TransportError as e:  # timeouts, dropped connections
            raise LLMError(f"Ollama did not respond in time: {type(e).__name__}") from e

        text = r.json()["message"]["content"]
        return LLMResponse(text=text, provider=self.name, model=model,
                           latency_ms=int((time.perf_counter() - start) * 1000))

    async def stream(self, messages: list[Message], temperature: float = 0.2, max_tokens: int = 1024,
                     model: str | None = None) -> AsyncIterator[str]:
        payload = {
            "model": model or self.model,
            "messages": [m.model_dump() for m in messages],
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=120, transport=self._transport) as client:
                async with client.stream("POST", "/api/chat", json=payload) as r:
                    if r.status_code != 200:
                        body = (await r.aread()).decode(errors="replace")
                        raise LLMError(f"Ollama error {r.status_code}: {body[:200]}")
                    async for line in r.aiter_lines():
                        if line.strip() and (piece := json.loads(line).get("message", {}).get("content")):
                            yield piece
        except httpx.ConnectError as e:
            raise LLMError("Ollama is not running. Start the Ollama app or run `ollama serve`.") from e
        except httpx.TransportError as e:
            raise LLMError(f"Ollama did not respond in time: {type(e).__name__}") from e
