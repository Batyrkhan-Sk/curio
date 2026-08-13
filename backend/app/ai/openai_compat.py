"""Client for OpenAI-compatible chat APIs — Groq and xAI.

Both expose the same `/chat/completions` shape, so one client serves both and
they differ only in base URL, key, and model pool.

Two deliberate choices:

* JSON is requested with plain `json_object` mode and the schema described in
  the prompt, rather than strict `json_schema` mode. Strict mode requires every
  property listed in `required` and `additionalProperties: false` throughout,
  which the Curio schemas do not satisfy — several fields are genuinely
  optional. Describing the shape in the prompt keeps one schema definition
  working across every provider.
* Model rotation on daily exhaustion, the same as Gemini. These providers also
  meter per model, so a pool multiplies the daily allowance.

Neither provider offers embeddings, so neither implements them. Embeddings
stay on Gemini — see the note in `llm.py` for why mixing them would be worse
than having none.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.ai import quota
from app.ai.gemini import (
    LLMQuotaExceeded,
    LLMTransient,
    LLMUnavailable,
    _loads_lenient,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

# Phrases that mean "you are out of allowance for the day" rather than "slow
# down". OpenAI-compatible APIs do not mark this in a structured field the
# way Gemini does, so it has to be read out of the message.
_DAILY_MARKERS = ("per day", "daily", "requests per day", "rpd", "tokens per day", "tpd")


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        model_pool: list[str],
        max_output_tokens: int | None = None,
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._preferred = model
        self._pool = model_pool
        self._max_output_tokens = max_output_tokens

    # -- model pool ---------------------------------------------------------

    @property
    def model_pool(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in [self._preferred, *self._pool]:
            if candidate and candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
        return ordered

    def available_models(self) -> list[str]:
        return [m for m in self.model_pool if not quota.is_exhausted(self.name, m)]

    @property
    def model(self) -> str:
        available = self.available_models()
        return available[0] if available else self._preferred

    @property
    def max_output_tokens(self) -> int:
        return self._max_output_tokens or settings.llm_max_output_tokens

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _require(self) -> None:
        if not self.enabled:
            raise LLMUnavailable(f"{self.name.upper()}_API_KEY is not set")

    # -- transport ----------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(LLMTransient),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=2, max=20),
        reraise=True,
    )
    async def _post(self, payload: dict[str, Any]) -> str:
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "authorization": f"Bearer {self.api_key}",
                        "content-type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise LLMTransient(f"network error calling {self.name}: {exc}") from exc

        if response.status_code == 429:
            message = _error_message(response)
            if any(marker in message.lower() for marker in _DAILY_MARKERS):
                raise LLMQuotaExceeded(f"{self.name}: {message[:220]}")
            # A per-minute limit, which backing off genuinely does fix.
            raise LLMTransient(f"{self.name} 429: {message[:200]}")
        if response.status_code >= 500:
            raise LLMTransient(f"{self.name} {response.status_code}: {response.text[:300]}")
        if response.status_code == 413:
            # Request too large for this model's rate tier. Not a quota
            # problem, so the model stays eligible — a smaller call may fit.
            raise LLMUnavailable(
                f"{self.name} request too large: {_error_message(response)[:220]}"
            )
        if response.status_code >= 400:
            raise LLMUnavailable(
                f"{self.name} {response.status_code}: {_error_message(response)[:300]}"
            )

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMUnavailable(f"{self.name} returned no choices")

        choice = choices[0]
        text = (choice.get("message", {}).get("content") or "").strip()

        if choice.get("finish_reason") == "length":
            raise LLMUnavailable(
                f"{self.name} hit the token limit before finishing. "
                "Raise LLM_MAX_OUTPUT_TOKENS."
            )
        if not text:
            raise LLMUnavailable(f"{self.name} returned an empty response")
        return text

    async def _post_rotating(self, payload: dict[str, Any]) -> str:
        candidates = self.available_models()
        if not candidates:
            when = quota.soonest_reset(self.name)
            raise LLMQuotaExceeded(
                f"All {len(self.model_pool)} {self.name} models are out of daily "
                f"quota. Resets around {when.isoformat(timespec='minutes')}."
            )

        last: Exception | None = None
        for index, model in enumerate(candidates):
            try:
                result = await self._post({**payload, "model": model})
                if index > 0:
                    logger.info("%s rotated to model %r", self.name, model)
                return result
            except LLMQuotaExceeded as exc:
                quota.mark_exhausted(self.name, model)
                last = exc
            except LLMUnavailable as exc:
                logger.warning("%s/%s rejected the request: %s", self.name, model, exc)
                last = exc

        raise LLMQuotaExceeded(
            f"All {len(candidates)} available {self.name} models failed. Last: {last}"
        )

    # -- generation ---------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.4,
        max_output_tokens: int | None = None,
    ) -> str:
        self._require()
        return await self._post_rotating(
            {
                "messages": _messages(prompt, system),
                "temperature": temperature,
                "max_tokens": max_output_tokens or self.max_output_tokens,
            }
        )

    async def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.3,
        max_output_tokens: int | None = None,
    ) -> Any:
        self._require()

        instruction = prompt
        if schema:
            instruction = (
                f"{prompt}\n\n"
                "Reply with a single JSON object matching this schema exactly. "
                "Include every required field. Output nothing but the JSON.\n\n"
                f"{json.dumps(schema, indent=2)}"
            )

        raw = await self._post_rotating(
            {
                "messages": _messages(instruction, system),
                "temperature": temperature,
                "max_tokens": max_output_tokens or self.max_output_tokens,
                "response_format": {"type": "json_object"},
            }
        )
        return _loads_lenient(raw)

    async def list_models(self) -> list[str]:
        """Ask the provider what this key can use — model ids move around."""
        self._require()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.base_url}/models",
                headers={"authorization": f"Bearer {self.api_key}"},
            )
        response.raise_for_status()
        return [m.get("id", "") for m in response.json().get("data", [])]


def _messages(prompt: str, system: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error or body)


groq = OpenAICompatibleClient(
    name="groq",
    api_key=settings.groq_api_key,
    base_url=settings.groq_base_url,
    model=settings.groq_model,
    model_pool=settings.groq_model_pool,
    max_output_tokens=settings.groq_max_output_tokens,
)

xai = OpenAICompatibleClient(
    name="xai",
    api_key=settings.xai_api_key,
    base_url=settings.xai_base_url,
    model=settings.xai_model,
    model_pool=[settings.xai_model],
)
