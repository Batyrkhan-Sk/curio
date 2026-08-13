"""Thin Gemini client over the Generative Language REST API.

Deliberately not using a vendor SDK: the only things that ever change are the
model id and the JSON shape, and both are cheaper to pin here than to chase
through an SDK upgrade. `settings.gemini_model` is a plain string — point it at
whatever model you actually have access to.

Every call raises `LLMUnavailable` when no API key is configured. Callers are
expected to catch it and degrade, never to crash: the platform is required to
work with the LLM switched off.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.ai import quota
from app.core.config import settings

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class LLMUnavailable(RuntimeError):
    """Raised when no key is configured, or the provider is unreachable."""


class LLMTransient(RuntimeError):
    """Retryable provider-side failure — a per-minute limit or a 5xx."""


class LLMQuotaExceeded(LLMUnavailable):
    """The daily allowance is gone.

    Distinguished from `LLMTransient` because retrying is not merely useless
    here, it is harmful: every retry is another request counted against a quota
    that will not reset for hours. Subclasses LLMUnavailable so every existing
    degrade-gracefully path already handles it.
    """

    def __init__(self, message: str, *, quota_id: str = "", limit: str = "") -> None:
        super().__init__(message)
        self.quota_id = quota_id
        self.limit = limit


class GeminiClient:
    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self._preferred = model or settings.gemini_model
        self.embedding_model = embedding_model or settings.gemini_embedding_model
        self.base_url = settings.gemini_base_url.rstrip("/")

    @property
    def model_pool(self) -> list[str]:
        """Preferred model first, then the configured pool, without repeats."""
        seen: set[str] = set()
        ordered: list[str] = []
        for name in [self._preferred, *settings.gemini_model_pool]:
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def available_models(self) -> list[str]:
        return [m for m in self.model_pool if not quota.is_exhausted("gemini", m)]

    @property
    def model(self) -> str:
        """Whichever model would serve the next request."""
        available = self.available_models()
        return available[0] if available else self._preferred

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _require(self) -> None:
        if not self.enabled:
            raise LLMUnavailable(
                "GEMINI_API_KEY is not set — AI synthesis is disabled. "
                "Curio serves curated content and keyword search instead."
            )

    # -- generation --------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(LLMTransient),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=2, max=20),
        reraise=True,
    )
    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{path}"
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "x-goog-api-key": self.api_key,
                        "content-type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:  # network-level
            raise LLMTransient(f"network error calling Gemini: {exc}") from exc

        if response.status_code == 429:
            quota = _daily_quota_violation(response)
            if quota is not None:
                raise LLMQuotaExceeded(
                    f"Daily Gemini quota exhausted for {quota.get('model', self.model)} "
                    f"({quota.get('limit')} requests/day on this plan). "
                    "It resets on Google's daily cycle; nothing else will help.",
                    quota_id=quota.get("quota_id", ""),
                    limit=str(quota.get("limit", "")),
                )
            # A per-minute limit, which backing off genuinely does fix.
            raise LLMTransient(f"gemini 429: {response.text[:200]}")
        if response.status_code >= 500:
            raise LLMTransient(f"gemini {response.status_code}: {response.text[:300]}")
        if response.status_code >= 400:
            raise LLMUnavailable(f"gemini {response.status_code}: {response.text[:300]}")
        return response.json()

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.4,
        max_output_tokens: int | None = None,
    ) -> str:
        """Return plain text for a single-turn prompt."""
        self._require()
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": _generation_config(
                temperature=temperature, max_output_tokens=max_output_tokens
            ),
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        return _extract_text(await self._generate_rotating(payload))

    async def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.3,
        max_output_tokens: int | None = None,
    ) -> Any:
        """Return parsed JSON, asking the model to constrain its own output."""
        self._require()
        generation_config = _generation_config(
            temperature=temperature, max_output_tokens=max_output_tokens
        )
        generation_config["responseMimeType"] = "application/json"
        if schema:
            generation_config["responseSchema"] = schema

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        raw = _extract_text(await self._generate_rotating(payload))
        return _loads_lenient(raw)

    async def _generate_rotating(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Try each model whose daily quota is not already spent."""
        candidates = self.available_models()
        if not candidates:
            when = quota.soonest_reset("gemini")
            raise LLMQuotaExceeded(
                f"All {len(self.model_pool)} Gemini models are out of daily "
                f"quota. Resets around {when.isoformat(timespec='minutes')}."
            )

        last: Exception | None = None
        for index, model in enumerate(candidates):
            try:
                data = await self._post(f"models/{model}:generateContent", payload)
                if index > 0:
                    logger.info("rotated to model %r", model)
                return data
            except LLMQuotaExceeded as exc:
                quota.mark_exhausted("gemini", model)
                last = exc
            except LLMUnavailable as exc:
                # A model that rejects the request — unsupported parameter, or
                # not available to this key — is not a quota problem, so it is
                # skipped without being marked exhausted.
                logger.warning("model %r rejected the request: %s", model, exc)
                last = exc

        raise LLMQuotaExceeded(
            f"All {len(candidates)} available Gemini models failed. Last: {last}"
        )

    # -- embeddings --------------------------------------------------------

    async def embed(self, text: str, *, task_type: str = "SEMANTIC_SIMILARITY") -> list[float]:
        vectors = await self.embed_many([text], task_type=task_type)
        return vectors[0]

    async def embed_many(
        self, texts: list[str], *, task_type: str = "SEMANTIC_SIMILARITY"
    ) -> list[list[float]]:
        """Embed a batch. Gemini caps batch size, so chunk conservatively."""
        self._require()
        if not texts:
            return []

        out: list[list[float]] = []
        for chunk in _chunks(texts, 64):
            payload = {
                "requests": [
                    {
                        "model": f"models/{self.embedding_model}",
                        "content": {"parts": [{"text": text[:20000]}]},
                        "taskType": task_type,
                        "outputDimensionality": settings.embedding_dim,
                    }
                    for text in chunk
                ]
            }
            data = await self._post(
                f"models/{self.embedding_model}:batchEmbedContents", payload
            )
            for item in data.get("embeddings", []):
                values = item.get("values", [])
                out.append(_normalize(values))
        return out


def _daily_quota_violation(response: httpx.Response) -> dict[str, Any] | None:
    """Pick a per-day quota violation out of a 429 body, if that is what it is."""
    try:
        details = response.json().get("error", {}).get("details", [])
    except ValueError:
        return None

    for detail in details:
        for violation in detail.get("violations", []) or []:
            quota_id = str(violation.get("quotaId", ""))
            if "PerDay" in quota_id:
                return {
                    "quota_id": quota_id,
                    "limit": violation.get("quotaValue", "?"),
                    "model": violation.get("quotaDimensions", {}).get("model", ""),
                }
    return None


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _normalize(values: list[float]) -> list[float]:
    """L2-normalise so cosine distance in pgvector behaves predictably.

    Gemini returns non-unit vectors when `outputDimensionality` truncates the
    full embedding, which quietly skews similarity scores if left alone.
    """
    magnitude = sum(v * v for v in values) ** 0.5
    if magnitude == 0:
        return values
    return [v / magnitude for v in values]


def _generation_config(*, temperature: float, max_output_tokens: int | None) -> dict[str, Any]:
    config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens or settings.llm_max_output_tokens,
    }
    if settings.gemini_thinking_level:
        config["thinkingConfig"] = {"thinkingLevel": settings.gemini_thinking_level}
    return config


def _extract_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback", {})
        raise LLMUnavailable(f"gemini returned no candidates: {feedback}")

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()

    # Truncation must be named. Otherwise it surfaces much later as an
    # inscrutable "Unterminated string" from the JSON parser, and the real
    # cause — a reasoning model spending the whole budget on thinking — is
    # invisible.
    if candidate.get("finishReason") == "MAX_TOKENS":
        usage = data.get("usageMetadata", {})
        raise LLMUnavailable(
            "gemini hit maxOutputTokens before finishing "
            f"(thinking used {usage.get('thoughtsTokenCount', 0)} tokens, "
            f"output {usage.get('candidatesTokenCount', 0)}). "
            "Raise LLM_MAX_OUTPUT_TOKENS or lower GEMINI_THINKING_LEVEL."
        )

    if not text:
        raise LLMUnavailable("gemini returned an empty response")
    return text


def _loads_lenient(raw: str) -> Any:
    """Parse JSON that may arrive wrapped in a markdown fence."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    stripped = _JSON_FENCE.sub("", raw).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = min(
            (i for i in (stripped.find("{"), stripped.find("[")) if i != -1),
            default=-1,
        )
        end = max(stripped.rfind("}"), stripped.rfind("]"))
        if start != -1 and end > start:
            return json.loads(stripped[start : end + 1])
        raise


gemini = GeminiClient()
