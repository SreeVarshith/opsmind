"""Any OpenAI-compatible API: Groq, OpenRouter, Cerebras, etc. (free tiers available)."""
import json
import time
from collections.abc import AsyncIterator

import httpx

from app.llm.base import LLMError, LLMProvider, LLMResponse, Message


class OpenAICompatProvider(LLMProvider):
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str, transport: httpx.AsyncBaseTransport | None = None,
                 extra_params: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._transport = transport
        self.extra_params = extra_params or {}  # provider-specific options, e.g. {"reasoning_effort": "low"}

    async def generate(self, messages: list[Message], temperature: float = 0.2, max_tokens: int = 1024,
                       model: str | None = None) -> LLMResponse:
        model = model or self.model
        if not self.api_key:
            raise LLMError("API_KEY is empty. Add your Groq key to the .env file.")

        payload = {
            "model": model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self.extra_params,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=60, transport=self._transport) as client:
                r = await client.post("/chat/completions", json=payload, headers=headers)
                r.raise_for_status()
        except httpx.ConnectError as e:
            raise LLMError(f"Cannot reach {self.base_url}. Check your internet connection.") from e
        except httpx.HTTPStatusError as e:
            raise self._status_error(e.response.status_code, e.response.text) from e
        except httpx.TransportError as e:  # timeouts, dropped connections
            raise LLMError(f"{self.base_url} did not respond in time: {type(e).__name__}") from e

        text = r.json()["choices"][0]["message"]["content"]
        return LLMResponse(text=text, provider=self.name, model=model,
                           latency_ms=int((time.perf_counter() - start) * 1000))

    @staticmethod
    def _status_error(code: int, body: str) -> LLMError:
        hint = {401: "invalid API key", 429: "rate limit hit, wait a minute", 404: "model name not found"}.get(code, "")
        return LLMError(f"API error {code} {hint}: {body[:200]}")

    async def stream(self, messages: list[Message], temperature: float = 0.2, max_tokens: int = 1024,
                     model: str | None = None) -> AsyncIterator[str]:
        if not self.api_key:
            raise LLMError("API_KEY is empty. Add your Groq key to the .env file.")
        payload = {
            "model": model or self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **self.extra_params,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=60, transport=self._transport) as client:
                async with client.stream("POST", "/chat/completions", json=payload, headers=headers) as r:
                    if r.status_code != 200:
                        raise self._status_error(r.status_code, (await r.aread()).decode(errors="replace"))
                    async for line in r.aiter_lines():
                        data = line.removeprefix("data:").strip()
                        if not line.startswith("data:") or data == "[DONE]":
                            continue
                        choices = json.loads(data).get("choices") or [{}]
                        if piece := (choices[0].get("delta") or {}).get("content"):
                            yield piece
        except httpx.ConnectError as e:
            raise LLMError(f"Cannot reach {self.base_url}. Check your internet connection.") from e
        except httpx.TransportError as e:
            raise LLMError(f"{self.base_url} did not respond in time: {type(e).__name__}") from e
