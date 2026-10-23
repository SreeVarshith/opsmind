"""Picks a provider and falls back to the other one if it fails.

Strategy:
  - "ollama"        -> local model first, Groq as backup
  - "openai_compat" -> Groq first, local model as backup
So the app keeps working when you are offline OR when the free API is rate limited.
"""
import logging

from app.core.config import Settings, get_settings
from app.llm.base import LLMError, LLMProvider, LLMResponse, Message
from app.llm.ollama import OllamaProvider
from app.llm.openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)


def build_providers(settings: Settings) -> dict[str, LLMProvider]:
    return {
        "ollama": OllamaProvider(settings.ollama_base_url, settings.ollama_model),
        "openai_compat": OpenAICompatProvider(
            settings.api_base_url, settings.api_key, settings.api_model,
            extra_params={"reasoning_effort": settings.api_reasoning_effort} if settings.api_reasoning_effort else None,
        ),
    }


class LLMRouter:
    def __init__(self, providers: dict[str, LLMProvider], default: str):
        if default not in providers:
            raise ValueError(f"Unknown LLM_PROVIDER '{default}'. Use one of {list(providers)}")
        self.providers = providers
        self.default = default

    def _order(self, preferred: str | None) -> list[str]:
        first = preferred or self.default
        return [first] + [p for p in self.providers if p != first]

    async def generate(self, messages: list[Message], provider: str | None = None, fallback: bool = True,
                       models: dict[str, str] | None = None, **kwargs) -> LLMResponse:
        """`models` picks a non-default model per provider, e.g. {"openai_compat": "openai/gpt-oss-20b"}.
        It is per provider so a fallback to another provider still uses a model that provider has."""
        order = self._order(provider)
        if not fallback:
            order = order[:1]

        errors = []
        for name in order:
            try:
                return await self.providers[name].generate(messages, model=(models or {}).get(name), **kwargs)
            except LLMError as e:
                logger.warning("LLM provider %s failed: %s", name, e)
                errors.append(f"{name}: {e}")
        raise LLMError(" | ".join(errors))


_router: LLMRouter | None = None


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        s = get_settings()
        _router = LLMRouter(build_providers(s), s.llm_provider)
    return _router
