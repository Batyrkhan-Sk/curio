"""A card with its strings already in the reader's language.

`LocalCard` deliberately duck-types the attributes `render` and `keyboards`
read off a real `Card`, so those modules never learn that translation exists —
they are handed something card-shaped and format it. Everything not worth
translating (ids, slugs, numbers, source URLs) is passed straight through.

Translation is per *view*, not per card. A card holds around fifty
translatable strings, and putting them all through the model before showing a
preview would make `/random` take ten seconds to answer. Each view asks for the
handful it needs instead; because the cache is keyed on the source text, the
title is translated once and is a cache hit in every view after the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Card
from app.services import translation


@dataclass(slots=True)
class LocalCategory:
    name: str
    slug: str = ""


@dataclass(slots=True)
class LocalCard:
    """Card-shaped, for `render` and `keyboards`. Only the fields a given view
    needs are translated; the rest carry the original values."""

    id: Any
    slug: str
    title: str
    one_sentence_answer: str
    summary: str
    reading_minutes: int
    difficulty: str
    confidence: float
    confidence_reason: str
    category: LocalCategory | None
    levels: list[dict[str, Any]] = field(default_factory=list)
    key_terms: list[dict[str, Any]] = field(default_factory=list)
    misconceptions: list[dict[str, Any]] = field(default_factory=list)
    sources: list[Any] = field(default_factory=list)
    image: dict[str, Any] = field(default_factory=dict)
    """Never translated — it is a URL and a licence, not prose. Carried so a
    view can be handed to the bot's picture helper without also passing the
    real row alongside it."""


def _shell(card: Card) -> LocalCard:
    """An untranslated copy — the starting point for every scope, and the
    whole answer when the reader is reading in English."""
    return LocalCard(
        id=card.id,
        slug=card.slug,
        title=card.title,
        one_sentence_answer=card.one_sentence_answer,
        summary=card.summary or "",
        reading_minutes=card.reading_minutes,
        difficulty=card.difficulty,
        confidence=card.confidence or 0.0,
        confidence_reason=card.confidence_reason or "",
        category=(
            LocalCategory(name=card.category.name, slug=card.category.slug)
            if card.category is not None
            else None
        ),
        levels=[dict(level) for level in (card.levels or [])],
        key_terms=[dict(term) for term in (card.key_terms or [])],
        misconceptions=[dict(myth) for myth in (card.misconceptions or [])],
        sources=list(card.sources or []),
        image=dict(card.image or {}),
    )


def _needs_translation(locale: str) -> bool:
    return translation.normalise_locale(locale) != translation.DEFAULT_LOCALE


async def localize_preview(
    session: AsyncSession, card: Card, locale: str
) -> LocalCard:
    """The fields the card preview and the search list show."""
    local = _shell(card)
    if not _needs_translation(locale):
        return local

    ordered = sorted(local.levels, key=lambda level: int(level.get("level", 0)))
    # The first level's label is the "start reading" button on this very
    # message, so it belongs to the preview even though its body does not.
    first_label = str(ordered[0].get("label", "")) if ordered else ""

    sources = [
        local.title,
        local.one_sentence_answer,
        local.summary,
        first_label,
    ]
    if local.category is not None:
        sources.append(local.category.name)

    done = await translation.translate_many(session, sources, locale)
    local.title, local.one_sentence_answer, local.summary = done[0], done[1], done[2]
    if ordered:
        ordered[0]["label"] = done[3]
        local.levels = ordered
    if local.category is not None:
        local.category.name = done[4]
    return local


async def localize_previews(
    session: AsyncSession, cards: list[Card], locale: str
) -> list[LocalCard]:
    """Several previews in one model call — for search results and /saved."""
    locals_ = [_shell(card) for card in cards]
    if not _needs_translation(locale) or not locals_:
        return locals_

    sources: list[str] = []
    for local in locals_:
        sources.extend([local.title, local.one_sentence_answer])

    done = await translation.translate_many(session, sources, locale)
    for index, local in enumerate(locals_):
        local.title = done[index * 2]
        local.one_sentence_answer = done[index * 2 + 1]
    return locals_


async def localize_level(
    session: AsyncSession, card: Card, locale: str, index: int
) -> LocalCard:
    """The title plus one explanation level — three strings, one call.

    Every level keeps its own entry so `render` can still count them; only the
    one being read is translated, because the others are a button press away
    and may never be opened.
    """
    local = _shell(card)
    if not _needs_translation(locale) or not local.levels:
        return local

    ordered = sorted(local.levels, key=lambda level: int(level.get("level", 0)))
    position = max(1, min(index, len(ordered)))
    level = ordered[position - 1]

    done = await translation.translate_many(
        session,
        [local.title, str(level.get("label", "")), str(level.get("body", ""))],
        locale,
    )
    local.title = done[0]
    level["label"] = done[1]
    level["body"] = done[2]

    # The first level's label is also the "start reading" button, so keep it
    # translated even when a later level is the one being shown.
    if position != 1:
        first = ordered[0]
        first["label"] = (
            await translation.translate_many(
                session, [str(first.get("label", ""))], locale
            )
        )[0]

    local.levels = ordered
    return local


async def localize_terms(
    session: AsyncSession, card: Card, locale: str
) -> LocalCard:
    local = _shell(card)
    if not _needs_translation(locale):
        return local

    terms = [term for term in local.key_terms if term.get("term")][:12]
    sources = [local.title]
    for term in terms:
        sources.append(str(term.get("term", "")))
        sources.append(
            str(term.get("plain_definition") or term.get("definition") or "")
        )

    done = await translation.translate_many(session, sources, locale)
    local.title = done[0]
    for offset, term in enumerate(terms):
        term["term"] = done[1 + offset * 2]
        term["plain_definition"] = done[2 + offset * 2]
        # The renderer prefers `plain_definition`; drop the alternates so a
        # translated card cannot fall back to an untranslated field.
        term.pop("definition", None)
        term.pop("meaning", None)
    local.key_terms = terms
    return local


async def localize_myths(
    session: AsyncSession, card: Card, locale: str
) -> LocalCard:
    local = _shell(card)
    if not _needs_translation(locale):
        return local

    myths = [m for m in local.misconceptions if m.get("myth") or m.get("claim")][:6]
    sources = [local.title]
    for myth in myths:
        sources.append(str(myth.get("myth") or myth.get("claim") or ""))
        sources.append(
            str(myth.get("reality") or myth.get("correction") or myth.get("truth") or "")
        )

    done = await translation.translate_many(session, sources, locale)
    local.title = done[0]
    for offset, myth in enumerate(myths):
        myth["myth"] = done[1 + offset * 2]
        myth["reality"] = done[2 + offset * 2]
        for alternate in ("claim", "correction", "truth"):
            myth.pop(alternate, None)
    local.misconceptions = myths
    return local


async def localize_sources(
    session: AsyncSession, card: Card, locale: str
) -> LocalCard:
    """Source titles stay as published — a citation you cannot look up is
    worse than one in the wrong language. Only the confidence note moves."""
    local = _shell(card)
    if not _needs_translation(locale):
        return local

    done = await translation.translate_many(
        session, [local.title, local.confidence_reason], locale
    )
    local.title, local.confidence_reason = done[0], done[1]
    return local
