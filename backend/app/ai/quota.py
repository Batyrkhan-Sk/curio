"""Tracking which models have spent their daily allowance.

Shared across providers and across client instances, because every provider
meters per model and every one of them resets on a daily boundary. Keeping
this in one place means a model discovered to be exhausted by one request is
not rediscovered — at the cost of another wasted request — by the next.

State is in memory only. A restart re-learns exhaustion by hitting a 429 once
per model, which is cheap and avoids needing a table for something that is
worthless after a few hours.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_exhausted: dict[str, datetime] = {}

# When each provider's daily counter rolls over, in UTC. Google meters on
# midnight Pacific; Groq and xAI use UTC. Approximating Pacific as 08:00 UTC
# errs an hour late, which only means retrying just after the reset rather
# than just before it — the harmless direction.
RESET_HOUR_UTC = {"gemini": 8, "groq": 0, "xai": 0}


def next_reset(provider: str) -> datetime:
    hour = RESET_HOUR_UTC.get(provider, 0)
    now = datetime.now(timezone.utc)
    reset = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if reset <= now:
        reset += timedelta(days=1)
    return reset


def _key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def mark_exhausted(provider: str, model: str) -> None:
    when = next_reset(provider)
    _exhausted[_key(provider, model)] = when
    logger.warning(
        "%s/%s out of daily quota; retrying after %s",
        provider,
        model,
        when.isoformat(timespec="minutes"),
    )


def is_exhausted(provider: str, model: str) -> bool:
    until = _exhausted.get(_key(provider, model))
    if until is None:
        return False
    if datetime.now(timezone.utc) >= until:
        del _exhausted[_key(provider, model)]
        return False
    return True


def soonest_reset(provider: str) -> datetime:
    """When the first model of this provider becomes usable again."""
    prefix = f"{provider}:"
    times = [when for key, when in _exhausted.items() if key.startswith(prefix)]
    return min(times) if times else next_reset(provider)


def snapshot() -> dict[str, str]:
    """Current exhaustion state, for status endpoints and debugging."""
    return {
        key: when.isoformat(timespec="minutes") for key, when in sorted(_exhausted.items())
    }
