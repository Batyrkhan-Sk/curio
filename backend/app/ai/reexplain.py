"""The "I still don't understand" path.

The requirement that shapes this module: never repeat yourself. Each time a
reader says it did not land, the explanation must change shape — not wording.
So the service tracks which approaches have already been spent on this card
and picks a genuinely different one each time.
"""

from __future__ import annotations

import logging

from app.ai import prompts
from app.ai.llm import LLMUnavailable, llm
from app.models import Card

logger = logging.getLogger(__name__)

# Ordered by how often they rescue a confused reader, not by sophistication.
MODE_LADDER = ["simpler", "analogy", "example", "steps", "visual", "first_principles"]

MODE_LABELS = {
    "simpler": "Simpler still",
    "analogy": "A different analogy",
    "example": "A concrete example",
    "steps": "Step by step",
    "visual": "As a picture",
    "first_principles": "From first principles",
}


def next_mode(tried: list[str]) -> str:
    """Choose an approach the reader has not seen yet."""
    for mode in MODE_LADDER:
        if mode not in tried:
            return mode
    # Everything has been tried; cycle back to the plainest one, which at least
    # gets a fresh generation rather than a cached repeat.
    return "simpler"


def previous_text(card: Card, tried: list[str], last_response: str | None) -> str:
    """What the reader has already read, so the model can avoid re-treading it."""
    if last_response:
        return last_response
    levels = card.levels or []
    return "\n\n".join(str(level.get("body", "")) for level in levels[:2])


async def reexplain(
    card: Card,
    *,
    tried: list[str] | None = None,
    last_response: str | None = None,
    mode: str | None = None,
) -> dict[str, str]:
    """Produce a fresh explanation in a shape the reader has not seen."""
    tried = tried or []
    chosen = mode or next_mode(tried)
    previous = previous_text(card, tried, last_response)

    if not llm.enabled:
        fallback = _offline_fallback(card, tried)
        if fallback is None:
            raise LLMUnavailable(
                "Every written explanation for this card has been shown. A live "
                "AI key is needed to generate a new one."
            )
        return fallback

    text = await llm.generate(
        prompts.reexplain_prompt(card.title, previous, chosen, attempt=len(tried) + 1),
        system=prompts.HOUSE_STYLE,
        temperature=0.75,
    )
    return {
        "mode": chosen,
        "label": MODE_LABELS.get(chosen, "Another way"),
        "body": text.strip(),
        "generated": "true",
    }


def _offline_fallback(card: Card, tried: list[str]) -> dict[str, str] | None:
    """With no LLM, walk the reader through the levels the card already has.

    This is honest rather than clever: the card genuinely contains five
    different framings, and showing the next unseen one is better than an
    apology.
    """
    levels = card.levels or []
    for level in levels:
        key = f"level-{level.get('level')}"
        if key not in tried:
            return {
                "mode": key,
                "label": str(level.get("label", "Another way")),
                "body": str(level.get("body", "")),
                "generated": "false",
            }
    return None
