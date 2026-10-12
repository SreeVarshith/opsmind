"""Tests use fake HTTP servers (httpx.MockTransport), so no GPU, internet or API key is needed."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm.base import LLMError, Message
from app.llm.ollama import OllamaProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.router import LLMRouter, get_router
from app.main import app

MSGS = [Message(role="user", content="hi")]


def fake_ollama(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api/chat"
    return httpx.Response(200, json={"message": {"role": "assistant", "content": "hello from ollama"}})


def fake_groq(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer test-key"
    return httpx.Response(200, json={"choices": [{"message": {"content": "hello from groq"}}]})


def down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def rate_limited(request: httpx.Request) -> httpx.Response:
    return httpx.Response(429, json={"error": "rate limit"})


def make_router(ollama_handler, groq_handler, default="ollama", key="test-key") -> LLMRouter:
    return LLMRouter(
        {
            "ollama": OllamaProvider("http://ollama", "llama3.2:3b", transport=httpx.MockTransport(ollama_handler)),
            "openai_compat": OpenAICompatProvider("http://groq", key, "llama-3.3-70b",
                                                  transport=httpx.MockTransport(groq_handler)),
        },
        default=default,
    )


def run(coro):
    return asyncio.run(coro)


def test_uses_default_provider():
    res = run(make_router(fake_ollama, fake_groq).generate(MSGS))
    assert res.text == "hello from ollama" and res.provider == "ollama"


def test_falls_back_to_groq_when_ollama_is_down():
    res = run(make_router(down, fake_groq).generate(MSGS))
    assert res.provider == "openai_compat"


def test_falls_back_to_ollama_when_groq_is_rate_limited():
    res = run(make_router(fake_ollama, rate_limited, default="openai_compat").generate(MSGS))
    assert res.provider == "ollama"


def test_no_fallback_raises():
    with pytest.raises(LLMError):
        run(make_router(down, fake_groq).generate(MSGS, fallback=False))


def test_missing_api_key_gives_clear_error():
    with pytest.raises(LLMError, match="API_KEY is empty"):
        run(make_router(fake_ollama, fake_groq, key="").generate(MSGS, provider="openai_compat", fallback=False))


def test_chat_endpoint():
    app.dependency_overrides[get_router] = lambda: make_router(fake_ollama, fake_groq)
    try:
        r = TestClient(app).post("/chat", json={"message": "hi"})
        assert r.status_code == 200
        assert r.json()["text"] == "hello from ollama"
    finally:
        app.dependency_overrides.clear()


def test_chat_endpoint_returns_503_when_all_providers_fail():
    app.dependency_overrides[get_router] = lambda: make_router(down, rate_limited)
    try:
        r = TestClient(app).post("/chat", json={"message": "hi"})
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()
