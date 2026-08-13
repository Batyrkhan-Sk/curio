"""Provider routing with failover.

Every AI feature in Curio calls this rather than a specific vendor. The order
is configurable (`LLM_PROVIDER_ORDER`, default `gemini,groq,xai`) and the rule is
simple: try each configured provider in turn, and move on when one is out of
quota, misconfigured, or persistently failing.

What does *not* fail over is embeddings. Vectors from two different models
occupy different spaces, so a corpus half-embedded by one and half by another
returns nonsense from every similarity query. Embeddings therefore stay with
whichever provider supports them, and semantic search switches off rather than
degrading invisibly — a wrong answer here is much worse than no answer.
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.gemini import (
    LLMQuotaExceeded,
    LLMTransient,
    LLMUnavailable,
    gemini,
)
from app.ai.openai_compat import groq, xai
from app.core.config import settings

logger = logging.getLogger(__name__)

# Anything a provider can raise that means "ask someone else".
FAILOVER_ERRORS = (LLMQuotaExceeded, LLMUnavailable, LLMTransient)


class LLMRouter:
    """Presents one provider-shaped interface over an ordered list of them."""

    def __init__(self) -> None:
        self._registry = {"gemini": gemini, "groq": groq, "xai": xai}

    @property
    def providers(self) -> list[Any]:
        """Configured, keyed providers in preference order."""
        order = [name.strip().lower() for name in settings.llm_provider_order]
        return [
            self._registry[name]
            for name in order
            if name in self._registry and self._registry[name].enabled
        ]

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    @property
    def model(self) -> str | None:
        active = self.providers
        return active[0].model if active else None

    def describe(self) -> list[dict[str, Any]]:
        order = [name.strip().lower() for name in settings.llm_provider_order]
        return [
            {
                "name": name,
                "configured": self._registry[name].enabled,
                "model": self._registry[name].model,
                "embeddings": name == "gemini",
            }
            for name in order
            if name in self._registry
        ]

    async def _attempt(self, method: str, *args: Any, **kwargs: Any) -> Any:
        providers = self.providers
        if not providers:
            raise LLMUnavailable(
                "No AI provider is configured. Set GEMINI_API_KEY, GROQ_API_KEY, "
                "or XAI_API_KEY to enable synthesis and re-explanation."
            )

        failures: list[str] = []
        for index, provider in enumerate(providers):
            try:
                result = await getattr(provider, method)(*args, **kwargs)
                if index > 0:
                    logger.info("served by fallback provider %r", provider.name)
                return result
            except FAILOVER_ERRORS as exc:
                failures.append(f"{provider.name}: {exc}")
                remaining = len(providers) - index - 1
                logger.warning(
                    "provider %r failed (%s)%s",
                    provider.name,
                    type(exc).__name__,
                    f", trying {remaining} more" if remaining else ", none left",
                )
                continue

        # Every provider is out. Report as quota-exceeded when that is what
        # actually happened, so callers can distinguish "come back tomorrow"
        # from "this is misconfigured".
        message = "All AI providers failed — " + "; ".join(failures)
        if any("quota" in failure.lower() for failure in failures):
            raise LLMQuotaExceeded(message)
        raise LLMUnavailable(message)

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        return await self._attempt("generate", prompt, **kwargs)

    async def generate_json(self, prompt: str, **kwargs: Any) -> Any:
        return await self._attempt("generate_json", prompt, **kwargs)

    # -- embeddings: single provider, never failed over -----------------------

    @property
    def embeddings_available(self) -> bool:
        return gemini.enabled

    async def embed(self, text: str, **kwargs: Any) -> list[float]:
        if not gemini.enabled:
            raise LLMUnavailable(
                "Embeddings need GEMINI_API_KEY. Neither Groq nor xAI offers an "
                "embeddings endpoint, and mixing embedding models would corrupt "
                "the vector index."
            )
        return await gemini.embed(text, **kwargs)

    async def embed_many(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        if not gemini.enabled:
            raise LLMUnavailable(
                "Embeddings need GEMINI_API_KEY. Neither Groq nor xAI offers an "
                "embeddings endpoint, and mixing embedding models would corrupt "
                "the vector index."
            )
        return await gemini.embed_many(texts, **kwargs)


llm = LLMRouter()

__all__ = ["LLMQuotaExceeded", "LLMTransient", "LLMUnavailable", "LLMRouter", "llm"]
