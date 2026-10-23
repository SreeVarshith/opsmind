"""Local models served by Ollama (runs on your own GPU, free, offline)."""
import time

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

        text = r.json()["message"]["content"]
        return LLMResponse(text=text, provider=self.name, model=model,
                           latency_ms=int((time.perf_counter() - start) * 1000))
