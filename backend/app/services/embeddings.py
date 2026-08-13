"""Embedding generation and vector similarity queries.

Every function here is a no-op when the LLM is disabled. Callers get empty
results rather than exceptions, so semantic features simply disappear instead
of breaking the request.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import LLMUnavailable, llm
from app.models import Card, Concept

logger = logging.getLogger(__name__)


def card_embedding_text(card: Card) -> str:
    """The text a card is embedded as.

    Weighted towards the question and the one-sentence answer: those are what a
    reader's query is actually similar to, while the deep levels add noise.
    """
    parts = [card.title, card.title, card.one_sentence_answer, card.summary]
    for level in (card.levels or [])[:2]:
        parts.append(str(level.get("body", ""))[:600])
    parts.extend(term.get("term", "") for term in (card.key_terms or []))
    parts.extend(card.tags or [])
    return "\n".join(p for p in parts if p)


async def embed_text(text: str, *, task_type: str = "SEMANTIC_SIMILARITY") -> list[float] | None:
    if not llm.embeddings_available:
        return None
    try:
        return await llm.embed(text, task_type=task_type)
    except LLMUnavailable as exc:
        logger.warning("embedding failed: %s", exc)
        return None


async def embed_query(text: str) -> list[float] | None:
    return await embed_text(text, task_type="RETRIEVAL_QUERY")


async def backfill_card_embeddings(session: AsyncSession, *, limit: int = 200) -> int:
    """Embed any published card that does not yet have a vector."""
    if not llm.embeddings_available:
        return 0

    result = await session.execute(
        select(Card).where(Card.embedding.is_(None)).limit(limit)
    )
    cards = list(result.scalars())
    if not cards:
        return 0

    try:
        vectors = await llm.embed_many(
            [card_embedding_text(c) for c in cards], task_type="RETRIEVAL_DOCUMENT"
        )
    except LLMUnavailable as exc:
        logger.warning("card embedding backfill skipped: %s", exc)
        return 0

    for card, vector in zip(cards, vectors, strict=False):
        card.embedding = vector
    await session.commit()
    logger.info("embedded %d cards", len(cards))
    return len(cards)


async def backfill_concept_embeddings(session: AsyncSession, *, limit: int = 400) -> int:
    if not llm.embeddings_available:
        return 0

    result = await session.execute(
        select(Concept).where(Concept.embedding.is_(None)).limit(limit)
    )
    concepts = list(result.scalars())
    if not concepts:
        return 0

    try:
        vectors = await llm.embed_many(
            [f"{c.name}. {c.plain_definition}" for c in concepts],
            task_type="RETRIEVAL_DOCUMENT",
        )
    except LLMUnavailable as exc:
        logger.warning("concept embedding backfill skipped: %s", exc)
        return 0

    for concept, vector in zip(concepts, vectors, strict=False):
        concept.embedding = vector
    await session.commit()
    return len(concepts)


async def similar_cards(
    session: AsyncSession,
    embedding: list[float],
    *,
    limit: int = 10,
    exclude_id: uuid.UUID | None = None,
    max_distance: float = 0.65,
) -> list[tuple[Card, float]]:
    """Nearest cards by cosine distance, closest first."""
    distance = Card.embedding.cosine_distance(embedding).label("distance")
    stmt = (
        select(Card, distance)
        .where(Card.embedding.is_not(None), Card.status == "published")
        .order_by(distance)
        .limit(limit)
    )
    if exclude_id is not None:
        stmt = stmt.where(Card.id != exclude_id)

    rows = await session.execute(stmt)
    return [(card, float(dist)) for card, dist in rows if float(dist) <= max_distance]
