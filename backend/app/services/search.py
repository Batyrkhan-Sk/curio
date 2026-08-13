"""Search: Meilisearch for words, pgvector for meaning, fused into one ranking.

Meilisearch alone cannot find "why walls slow Wi-Fi" from the query "wifi
weak bedroom". Vectors alone are fuzzy about exact terms and typos. Running
both and fusing with Reciprocal Rank Fusion gets the behaviour the spec asks
for: searching "wifi" surfaces the wall-attenuation card, the 5 GHz range card,
and the channel-selection card.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from meilisearch_python_sdk import AsyncClient
from meilisearch_python_sdk.models.settings import MeilisearchSettings, TypoTolerance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import Card
from app.services.embeddings import embed_query, similar_cards

logger = logging.getLogger(__name__)

RRF_K = 60
"""Reciprocal Rank Fusion damping. 60 is the value from the original paper and
keeps a strong result from either engine from dominating the other."""


@dataclass(slots=True)
class SearchHit:
    card: Card
    score: float
    matched_by: list[str]


def _client() -> AsyncClient:
    return AsyncClient(settings.meili_url, settings.meili_master_key)


def card_document(card: Card) -> dict[str, Any]:
    """Flatten a card for the keyword index.

    Level bodies are included so a phrase buried in the technical explanation is
    still findable, but they sit last in the searchable-attribute order so they
    never outrank a title match.
    """
    return {
        "id": str(card.id),
        "slug": card.slug,
        "title": card.title,
        "one_sentence_answer": card.one_sentence_answer,
        "summary": card.summary,
        "category": card.category.slug if card.category else "",
        "category_name": card.category.name if card.category else "",
        "tags": list(card.tags or []),
        "shelves": list(card.shelves or []),
        "key_terms": [t.get("term", "") for t in (card.key_terms or [])],
        "concepts": [t.get("term", "") for t in (card.key_terms or [])],
        "difficulty": card.difficulty,
        "reading_minutes": card.reading_minutes,
        "curiosity_score": card.curiosity_score,
        "confidence": card.confidence,
        "level_bodies": [str(level.get("body", "")) for level in (card.levels or [])],
    }


async def ensure_index() -> None:
    """Create and configure the index. Safe to call on every boot."""
    try:
        async with _client() as client:
            index = client.index(settings.meili_cards_index)
            await index.update_settings(
                MeilisearchSettings(
                    searchable_attributes=[
                        "title",
                        "one_sentence_answer",
                        "key_terms",
                        "tags",
                        "summary",
                        "category_name",
                        "level_bodies",
                    ],
                    filterable_attributes=[
                        "category",
                        "tags",
                        "shelves",
                        "difficulty",
                        "reading_minutes",
                    ],
                    sortable_attributes=["curiosity_score", "reading_minutes", "confidence"],
                    ranking_rules=[
                        "words",
                        "typo",
                        "proximity",
                        "attribute",
                        "sort",
                        "exactness",
                        "curiosity_score:desc",
                    ],
                    typo_tolerance=TypoTolerance(enabled=True),
                    synonyms={
                        "wifi": ["wi-fi", "wireless", "wlan"],
                        "cpu": ["processor", "chip"],
                        "ram": ["memory"],
                        "ssd": ["solid state drive", "flash storage"],
                        "plane": ["airplane", "aircraft", "aeroplane"],
                        "gps": ["satellite navigation", "geolocation"],
                    },
                )
            )
        logger.info("meilisearch index ready")
    except Exception as exc:  # search must never block startup
        logger.warning("could not configure meilisearch: %s", exc)


async def index_cards(cards: list[Card]) -> None:
    if not cards:
        return
    try:
        async with _client() as client:
            index = client.index(settings.meili_cards_index)
            await index.add_documents([card_document(c) for c in cards], primary_key="id")
    except Exception as exc:
        logger.warning("meilisearch indexing failed: %s", exc)


async def reindex_all(session: AsyncSession) -> int:
    result = await session.execute(
        select(Card)
        .options(selectinload(Card.category))
        .where(Card.status == "published")
    )
    cards = list(result.scalars().unique())
    await index_cards(cards)
    return len(cards)


async def keyword_search(
    query: str,
    *,
    limit: int = 20,
    category: str | None = None,
) -> list[str]:
    """Return card ids in relevance order."""
    try:
        async with _client() as client:
            index = client.index(settings.meili_cards_index)
            results = await index.search(
                query,
                limit=limit,
                filter=f'category = "{category}"' if category else None,
            )
        return [hit["id"] for hit in results.hits]
    except Exception as exc:
        logger.warning("meilisearch query failed, falling back to vectors: %s", exc)
        return []


async def hybrid_search(
    session: AsyncSession,
    query: str,
    *,
    limit: int = 20,
    category: str | None = None,
) -> list[SearchHit]:
    keyword_ids = await keyword_search(query, limit=limit * 2, category=category)

    semantic_ids: list[str] = []
    embedding = await embed_query(query)
    if embedding is not None:
        neighbours = await similar_cards(session, embedding, limit=limit * 2, max_distance=0.8)
        semantic_ids = [str(card.id) for card, _ in neighbours]

    if not keyword_ids and not semantic_ids:
        return await _fallback_ilike(session, query, limit=limit, category=category)

    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}
    for rank, card_id in enumerate(keyword_ids):
        scores[card_id] = scores.get(card_id, 0.0) + 1.0 / (RRF_K + rank + 1)
        matched.setdefault(card_id, []).append("keyword")
    for rank, card_id in enumerate(semantic_ids):
        scores[card_id] = scores.get(card_id, 0.0) + 1.0 / (RRF_K + rank + 1)
        matched.setdefault(card_id, []).append("meaning")

    ordered = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:limit]
    if not ordered:
        return []

    rows = await session.execute(
        select(Card).options(selectinload(Card.category)).where(Card.id.in_(ordered))
    )
    by_id = {str(card.id): card for card in rows.scalars().unique()}
    return [
        SearchHit(card=by_id[cid], score=scores[cid], matched_by=matched[cid])
        for cid in ordered
        if cid in by_id
    ]


async def _fallback_ilike(
    session: AsyncSession,
    query: str,
    *,
    limit: int,
    category: str | None,
) -> list[SearchHit]:
    """Last resort when Meilisearch is down and embeddings are unavailable."""
    pattern = f"%{query.strip()}%"
    stmt = (
        select(Card)
        .options(selectinload(Card.category))
        .where(
            Card.status == "published",
            Card.title.ilike(pattern) | Card.one_sentence_answer.ilike(pattern),
        )
        .order_by(Card.curiosity_score.desc())
        .limit(limit)
    )
    if category:
        stmt = stmt.join(Card.category).where(Card.category.has(slug=category))
    rows = await session.execute(stmt)
    return [SearchHit(card=c, score=0.0, matched_by=["text"]) for c in rows.scalars().unique()]


async def suggest(query: str, *, limit: int = 6) -> list[str]:
    """Typeahead question suggestions."""
    try:
        async with _client() as client:
            index = client.index(settings.meili_cards_index)
            results = await index.search(query, limit=limit, attributes_to_retrieve=["title"])
        return [hit["title"] for hit in results.hits]
    except Exception:
        return []
