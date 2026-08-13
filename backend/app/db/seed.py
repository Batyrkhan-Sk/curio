"""Load the curated corpus.

The seed corpus exists for two reasons beyond having something to look at.
It is the reference for what a good card is — every prompt in `app/ai/prompts.py`
is written to produce something of this shape and depth — and it makes the
platform fully functional with no API key, which was an explicit requirement.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slugify import slugify
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Card, Category, Source
from app.services import discovery as discovery_service
from app.services import graph as graph_service
from app.services import search as search_service

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).parent / "seed"


async def seed_all(session: AsyncSession, *, force: bool = False) -> dict:
    """Idempotent. Existing cards are left alone unless `force` is set."""
    categories = await _seed_categories(session)
    cards = await _seed_cards(session, force=force)
    links = await _build_graph(session)
    await session.commit()

    indexed = await search_service.reindex_all(session)

    result = {
        "categories": categories,
        "cards": cards,
        "graph_links": links,
        "indexed": indexed,
    }
    logger.info("seed complete: %s", result)
    return result


async def _seed_categories(session: AsyncSession) -> int:
    payload = json.loads((SEED_DIR / "categories.json").read_text())
    created = 0
    for spec in payload:
        existing = await session.scalar(
            select(Category).where(Category.slug == spec["slug"])
        )
        if existing is not None:
            continue
        session.add(Category(**spec))
        created += 1
    await session.flush()
    return created


def _load_card_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for path in sorted(SEED_DIR.glob("cards_*.json")):
        specs.extend(json.loads(path.read_text()))
    return specs


async def _seed_cards(session: AsyncSession, *, force: bool) -> int:
    specs = _load_card_specs()
    written = 0

    for spec in specs:
        slug = slugify(spec["title"])[:220]
        existing = await session.scalar(select(Card).where(Card.slug == slug))
        if existing is not None and not force:
            continue

        category = await session.scalar(
            select(Category).where(Category.slug == spec["category_slug"])
        )
        card = existing or Card(slug=slug)
        card.title = spec["title"]
        card.one_sentence_answer = spec["one_sentence_answer"]
        card.summary = spec.get("summary", "")
        card.category = category
        card.levels = spec.get("levels", [])
        card.key_terms = spec.get("key_terms", [])
        card.misconceptions = spec.get("misconceptions", [])
        card.why_it_matters = spec.get("why_it_matters", "")
        card.historical_background = spec.get("historical_background", {})
        card.diagrams = spec.get("diagrams", [])
        card.next_steps = spec.get("next_steps", [])
        card.tags = spec.get("tags", [])
        card.difficulty = spec.get("difficulty", "beginner")
        card.reading_minutes = spec.get("reading_minutes", 5)
        card.curiosity_score = spec.get("curiosity_score", 0.5)
        card.confidence = spec.get("confidence", 0.8)
        card.confidence_reason = spec.get("confidence_reason", "")
        card.verified_at = datetime.now(timezone.utc)
        card.status = "published"
        card.origin = "curated"
        card.shelves = discovery_service.shelves_for_card(
            card, category_slug=spec["category_slug"], is_new=False
        )

        if existing is None:
            session.add(card)
        await session.flush()

        # Explicit DELETE rather than iterating card.sources: after flush the
        # card is persistent, so touching the collection would emit a lazy load
        # and async SQLAlchemy refuses those outside a greenlet context.
        await session.execute(delete(Source).where(Source.card_id == card.id))
        for source in spec.get("sources", []):
            session.add(Source(card_id=card.id, **source))

        for concept_spec in spec.get("concepts", []):
            concept = await graph_service.upsert_concept(
                session,
                concept_spec["name"],
                plain_definition=concept_spec.get("plain_definition", ""),
                category_slug=spec["category_slug"],
            )
            await graph_service.link_card_concept(
                session, card.id, concept.id, role=concept_spec.get("role", "covers")
            )

        written += 1

    await session.flush()
    return written


async def _build_graph(session: AsyncSession) -> int:
    """Connect the corpus: explicit related questions first, then shared concepts."""
    specs = {slugify(s["title"])[:220]: s for s in _load_card_specs()}
    created = 0

    for slug, spec in specs.items():
        card = await session.scalar(select(Card).where(Card.slug == slug))
        if card is None:
            continue

        for question in spec.get("related_questions", []):
            target_slug = slugify(question)[:220]
            target = await session.scalar(select(Card).where(Card.slug == target_slug))
            if target is None or target.id == card.id:
                continue
            await graph_service.link_cards(
                session,
                card.id,
                target.id,
                relation="related",
                weight=1.0,
                reason="A natural next question",
            )
            created += 1

        created += await graph_service.connect_by_shared_concepts(session, card)

    await session.flush()
    return created


async def is_empty(session: AsyncSession) -> bool:
    count = await session.scalar(select(func.count(Card.id)))
    return not count
