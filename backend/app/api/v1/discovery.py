"""The homepage feed, plus the single-card discovery endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, OptionalProfile, not_found
from app.ai.llm import llm
from app.models import Card, Question
from app.schemas.card import (
    CardSummary,
    DiscoveredQuestionOut,
    DiscoveryFeed,
    DiscoveryQueue,
    Shelf,
)
from app.services import discovery as discovery_service
from app.services import personalization

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/feed", response_model=DiscoveryFeed)
async def feed(
    session: DbSession,
    profile: OptionalProfile,
    per_shelf: int = Query(default=8, ge=3, le=20),
    mode: str = Query(
        default=discovery_service.DEFAULT_MODE,
        description="'interesting' for curiosity, 'useful' for the practical lens",
    ),
) -> DiscoveryFeed:
    """Every shelf of one mode, in the order that suits this reader."""
    mode = discovery_service.resolve_mode(mode)
    built = await discovery_service.build_feed(
        session, profile=profile, per_shelf=per_shelf, mode=mode
    )

    shelves = [
        Shelf(
            key=spec.key,
            title=spec.title,
            subtitle=spec.subtitle,
            cards=[CardSummary.model_validate(c) for c in cards],
        )
        for spec, cards in built
    ]

    # Personal recommendations are drawn from everything the reader has read,
    # which in useful mode would quietly reintroduce the cards the mode exists
    # to filter out. It stays an interesting-mode shelf.
    if profile is not None and mode == "interesting":
        recommended = await personalization.recommend(session, profile, limit=per_shelf)
        if recommended:
            shelves.insert(
                1,
                Shelf(
                    key="for-you",
                    title="Picked up from what you've read",
                    subtitle="Including a few things deliberately outside your usual",
                    cards=[CardSummary.model_validate(c) for c in recommended],
                ),
            )

    return DiscoveryFeed(
        shelves=shelves, generated_at=datetime.now(timezone.utc), mode=mode
    )


@router.get("/shelf/{key}", response_model=Shelf)
async def shelf(
    key: str,
    session: DbSession,
    limit: int = Query(default=24, ge=1, le=60),
    mode: str = Query(default=discovery_service.DEFAULT_MODE),
) -> Shelf:
    spec = discovery_service.SHELF_BY_KEY.get(key)
    if spec is None:
        raise not_found("Shelf")

    cards = await discovery_service.shelf_cards(session, key, limit=limit, mode=mode)
    return Shelf(
        key=spec.key,
        title=spec.title,
        subtitle=spec.subtitle,
        cards=[CardSummary.model_validate(c) for c in cards],
    )


@router.get("/questions", response_model=DiscoveryQueue)
async def discovered_questions(
    session: DbSession,
    status: str = Query(default="all", pattern="^(all|pending|published|rejected)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DiscoveryQueue:
    """The raw curiosity the platform has collected but not yet written up.

    This is the input side of the pipeline. Most of it is noise and will be
    rejected at triage; showing it anyway is the honest way to represent what
    "indexing curiosity" actually involves.
    """
    counts = await session.execute(
        select(
            func.count(Question.id),
            func.count(Question.id).filter(Question.card_id.is_not(None)),
            func.count(Question.id).filter(
                Question.processed.is_(True), Question.card_id.is_(None)
            ),
            func.count(Question.id).filter(Question.occurrences > 1),
        )
    )
    total, published, rejected, repeated = counts.one()

    source_rows = await session.execute(
        select(Question.source_name, func.count(Question.id))
        .group_by(Question.source_name)
        .order_by(func.count(Question.id).desc())
    )
    sources = [{"name": name, "count": int(count)} for name, count in source_rows]

    stmt = select(Question, Card.slug).outerjoin(Card, Question.card_id == Card.id)
    if status == "pending":
        stmt = stmt.where(Question.processed.is_(False))
    elif status == "published":
        stmt = stmt.where(Question.card_id.is_not(None))
    elif status == "rejected":
        stmt = stmt.where(Question.processed.is_(True), Question.card_id.is_(None))

    # Most-repeated first: a question asked in five places is the one most
    # worth writing up, and it is what a reader wants to see at the top.
    rows = await session.execute(
        stmt.order_by(Question.occurrences.desc(), Question.engagement.desc())
        .offset(offset)
        .limit(limit)
    )

    items = []
    for question, card_slug in rows:
        if question.card_id is not None:
            state = "published"
        elif question.processed:
            state = "rejected"
        else:
            state = "pending"
        items.append(
            DiscoveredQuestionOut(
                id=question.id,
                raw_text=question.raw_text,
                source_name=question.source_name,
                source_url=question.source_url,
                occurrences=question.occurrences,
                engagement=question.engagement,
                first_seen_at=question.first_seen_at,
                last_seen_at=question.last_seen_at,
                status=state,
                card_slug=card_slug,
                rejected_reason=question.rejected_reason,
            )
        )

    return DiscoveryQueue(
        total=int(total),
        pending=int(total) - int(published) - int(rejected),
        published=int(published),
        rejected=int(rejected),
        repeated=int(repeated),
        sources=sources,
        items=items,
        llm_enabled=llm.enabled,
    )


@router.get("/random", response_model=CardSummary)
async def random_card(
    session: DbSession,
    profile: OptionalProfile,
    mode: str = Query(default=discovery_service.DEFAULT_MODE),
) -> CardSummary:
    """Something unexpected — but never what the reader was just shown."""
    card = await discovery_service.random_card(session, profile=profile, mode=mode)
    if card is None:
        raise not_found()
    return CardSummary.model_validate(card)
