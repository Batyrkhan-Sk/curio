"""Card reading endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, OptionalProfile, not_found
from app.models import Card, Category
from app.schemas.card import (
    AskedAt,
    CardDetail,
    CardSummary,
    CategoryOut,
    RelatedCard,
)
from app.services import discovery, graph, personalization

router = APIRouter(prefix="/cards", tags=["cards"])


@router.get("", response_model=list[CardSummary])
async def list_cards(
    session: DbSession,
    category: str | None = None,
    difficulty: str | None = None,
    tag: str | None = None,
    limit: int = Query(default=24, le=100),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="curiosity", pattern="^(curiosity|newest|saved|reading_time)$"),
) -> list[CardSummary]:
    stmt = (
        select(Card)
        .options(selectinload(Card.category))
        .where(Card.status == "published")
    )
    if category:
        stmt = stmt.join(Category, Card.category_id == Category.id).where(
            Category.slug == category
        )
    if difficulty:
        stmt = stmt.where(Card.difficulty == difficulty)
    if tag:
        stmt = stmt.where(Card.tags.any(tag.lower()))

    order = {
        "curiosity": Card.curiosity_score.desc(),
        "newest": Card.created_at.desc(),
        "saved": Card.save_count.desc(),
        "reading_time": Card.reading_minutes.asc(),
    }[sort]

    rows = await session.execute(stmt.order_by(order).offset(offset).limit(limit))
    return [CardSummary.model_validate(c) for c in rows.scalars().unique()]


@router.get("/{slug}", response_model=CardDetail)
async def get_card(
    slug: str,
    session: DbSession,
    profile: OptionalProfile,
) -> CardDetail:
    card = await session.scalar(
        select(Card)
        # Both relationships are eager-loaded explicitly: CardDetail serialises
        # them, and an async session cannot satisfy a lazy load at that point.
        .options(
            selectinload(Card.category),
            selectinload(Card.sources),
            # The observed questions are what let the card say where it came
            # from, rather than making the reader take "discovered" on trust.
            selectinload(Card.questions),
        )
        .where(Card.slug == slug)
    )
    if card is None or card.status != "published":
        raise not_found()

    # Serialise before recording the view. Bumping the counters marks the row
    # dirty, and `updated_at` carries an onupdate default, so after the flush
    # that column is expired and reading it would need another round trip that
    # an async session cannot make mid-serialisation.
    detail = CardDetail.model_validate(card)
    if detail.image is not None:
        # The stored URL points at Wikimedia or Reddit; readers get Curio's own
        # path instead, so the service worker can cache it and the upstream host
        # never sees the reader. Relative, because the frontend proxies /api.
        detail.image.url = f"/api/v1/media/{card.id}"
    detail.asked_at = [
        AskedAt.model_validate(q)
        for q in sorted(
            card.questions, key=lambda q: (q.occurrences, q.engagement), reverse=True
        )
    ]
    detail.related = await _related(session, card, profile)

    await discovery.record_view(session, card)
    await session.commit()
    return detail


async def _related(session: DbSession, card: Card, profile) -> list[RelatedCard]:
    """Related questions, re-ordered for this reader when we know them."""
    pairs = await graph.related_cards(session, card.id, limit=8)

    related: list[RelatedCard] = []
    for other, link in pairs:
        item = RelatedCard.model_validate(other)
        item.relation = link.relation
        item.reason = link.reason
        related.append(item)

    if profile is not None:
        suggested = await personalization.next_in_learning_path(
            session, profile, card, limit=3
        )
        suggested_ids = {c.id for c in suggested}
        # Cards that build on what this reader already knows go first.
        related.sort(key=lambda r: 0 if r.id in suggested_ids else 1)

    return related


@router.get("/{slug}/graph")
async def card_graph(
    slug: str,
    session: DbSession,
    depth: int = Query(default=2, ge=1, le=3),
    max_nodes: int = Query(default=40, ge=5, le=120),
) -> dict:
    card = await session.scalar(select(Card).where(Card.slug == slug))
    if card is None:
        raise not_found()

    view = await graph.neighbourhood(session, card.id, depth=depth, max_nodes=max_nodes)
    return {
        "root": str(card.id),
        # GraphNode is a slots dataclass, so asdict rather than __dict__.
        "nodes": [asdict(node) for node in view.nodes],
        "edges": view.edges,
    }


categories_router = APIRouter(prefix="/categories", tags=["categories"])


@categories_router.get("", response_model=list[dict])
async def list_categories(session: DbSession) -> list[dict]:
    """Categories with live card counts, so empty ones can be hidden."""
    rows = await session.execute(
        select(Category, func.count(Card.id))
        .outerjoin(Card, (Card.category_id == Category.id) & (Card.status == "published"))
        .group_by(Category.id)
        .order_by(Category.sort_order, Category.name)
    )
    return [
        {**CategoryOut.model_validate(category).model_dump(), "card_count": int(count)}
        for category, count in rows
    ]
