"""The reader's own data: profile, saves, stats, notifications."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentProfile, DbSession, not_found
from app.core.config import settings
from app.models import Card, PushSubscription
from app.schemas.card import CardSummary
from app.schemas.profile import (
    InteractionIn,
    ProfileOut,
    ProfileUpdate,
    PushSubscriptionIn,
    StatsOut,
)
from app.services import personalization, push

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=ProfileOut)
async def get_profile(profile: CurrentProfile) -> ProfileOut:
    return ProfileOut.model_validate(profile)


@router.patch("", response_model=ProfileOut)
async def update_profile(
    body: ProfileUpdate, profile: CurrentProfile, session: DbSession
) -> ProfileOut:
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(profile, field, value)
    await session.commit()
    return ProfileOut.model_validate(profile)


@router.post("/interactions", status_code=status.HTTP_204_NO_CONTENT)
async def record_interaction(
    body: InteractionIn, profile: CurrentProfile, session: DbSession
) -> Response:
    card = await session.scalar(
        select(Card).options(selectinload(Card.category)).where(Card.id == body.card_id)
    )
    if card is None:
        raise not_found()

    await personalization.record_interaction(
        session, profile, card, kind=body.kind, level=body.level, seconds=body.seconds
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/saved", response_model=list[CardSummary])
async def saved(profile: CurrentProfile, session: DbSession) -> list[CardSummary]:
    cards = await personalization.saved_cards(session, profile)
    return [CardSummary.model_validate(c) for c in cards]


@router.get("/stats", response_model=StatsOut)
async def stats(profile: CurrentProfile, session: DbSession) -> StatsOut:
    return StatsOut(**await personalization.stats(session, profile))


@router.get("/recommendations", response_model=list[CardSummary])
async def recommendations(
    profile: CurrentProfile, session: DbSession, limit: int = 12
) -> list[CardSummary]:
    cards = await personalization.recommend(session, profile, limit=limit)
    return [CardSummary.model_validate(c) for c in cards]


# ---------------------------------------------------------------------------
# Push notifications
# ---------------------------------------------------------------------------


@router.get("/push/key")
async def push_key() -> dict:
    """The VAPID public key the browser needs to subscribe."""
    return {"public_key": settings.vapid_public_key, "enabled": settings.push_enabled}


@router.post("/push/subscribe", status_code=status.HTTP_201_CREATED)
async def subscribe(
    body: PushSubscriptionIn, profile: CurrentProfile, session: DbSession
) -> dict:
    existing = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    if existing is not None:
        # The same browser can re-subscribe after a profile reset; re-point it
        # rather than creating a duplicate row.
        existing.profile_id = profile.id
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
        existing.failure_count = 0
    else:
        session.add(
            PushSubscription(
                profile_id=profile.id,
                endpoint=body.endpoint,
                p256dh=body.keys.p256dh,
                auth=body.keys.auth,
                user_agent=body.user_agent,
            )
        )
    await session.commit()
    return {"status": "subscribed"}


@router.delete("/push/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(endpoint: str, session: DbSession) -> Response:
    subscription = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    if subscription is not None:
        await session.delete(subscription)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/push/test")
async def send_test(profile: CurrentProfile, session: DbSession) -> dict:
    """Send this reader whatever they would get today, right now."""
    if not settings.push_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push is not configured. Generate VAPID keys with "
            "`docker compose run --rm api python -m app.cli vapid`.",
        )

    notification = await push.compose_for(session, profile)
    if notification is None:
        notification = push.Notification(
            title="Curio is connected",
            body="Notifications are working. You'll get one a day at most.",
            url="/",
        )
    delivered = await push.send_to_profile(session, profile, notification)
    await session.commit()
    return {"delivered": delivered, "title": notification.title, "body": notification.body}
