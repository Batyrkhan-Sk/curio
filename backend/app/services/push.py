"""Web push delivery and notification copywriting.

The brief's constraint: notifications should encourage learning, not addiction.
Concretely that means at most one a day, never a streak-loss threat, never a
manufactured-urgency verb, and every one names a specific thing to learn so it
can be judged on its own merits before being opened.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import Card, Interaction, Profile, PushSubscription
from app.services import personalization

logger = logging.getLogger(__name__)

MAX_FAILURES = 5
"""After this many consecutive failures a subscription is deleted. Browsers
recycle endpoints, and pushing to a dead one forever is just noise."""


@dataclass(slots=True)
class Notification:
    title: str
    body: str
    url: str
    tag: str = "curio"

    def payload(self) -> str:
        return json.dumps(
            {
                "title": self.title,
                "body": self.body,
                "url": self.url,
                "tag": self.tag,
            }
        )


async def compose_for(session: AsyncSession, profile: Profile) -> Notification | None:
    """Pick the single most worthwhile thing to tell this reader today."""
    builders = (
        _continue_a_thread,
        _unexplored_territory,
        _daily_curiosity,
    )
    for builder in builders:
        notification = await builder(session, profile)
        if notification is not None:
            return notification
    return None


async def _continue_a_thread(
    session: AsyncSession, profile: Profile
) -> Notification | None:
    """"You recently learned about RAM. Today you might enjoy CPU cache." """
    recent = await session.scalar(
        select(Interaction)
        .where(Interaction.profile_id == profile.id, Interaction.kind.in_(["view", "complete"]))
        .order_by(Interaction.created_at.desc())
        .limit(1)
    )
    if recent is None:
        return None

    last_card = await session.scalar(
        select(Card).options(selectinload(Card.category)).where(Card.id == recent.card_id)
    )
    if last_card is None:
        return None

    upcoming = await personalization.next_in_learning_path(
        session, profile, last_card, limit=1
    )
    if not upcoming:
        return None

    nxt = upcoming[0]
    subject = _subject_of(last_card)
    return Notification(
        title="This follows on from what you read",
        body=f"You looked at {subject}. {nxt.title}",
        url=f"/q/{nxt.slug}",
        tag="curio-thread",
    )


async def _unexplored_territory(
    session: AsyncSession, profile: Profile
) -> Notification | None:
    """"You've never explored why GPS isn't perfectly accurate." """
    if random.random() > 0.4:  # noqa: S311 — variety, not security
        return None

    category = await personalization.unexplored_category(session, profile)
    if category is None:
        return None

    card = await session.scalar(
        select(Card)
        .options(selectinload(Card.category))
        .where(Card.category_id == category.id, Card.status == "published")
        .order_by(Card.curiosity_score.desc())
        .limit(1)
    )
    if card is None:
        return None

    return Notification(
        title=f"You've never explored {category.name.lower()}",
        body=card.title,
        url=f"/q/{card.slug}",
        tag="curio-explore",
    )


async def _daily_curiosity(session: AsyncSession, profile: Profile) -> Notification | None:
    seen = set(
        (
            await session.execute(
                select(Interaction.card_id).where(Interaction.profile_id == profile.id)
            )
        ).scalars()
    )
    recommendations = await personalization.recommend(session, profile, limit=6)
    fresh = [c for c in recommendations if c.id not in seen]
    if not fresh:
        return None

    card = fresh[0]
    return Notification(
        title="Today's curiosity",
        body=card.title,
        url=f"/q/{card.slug}",
        tag="curio-daily",
    )


def _subject_of(card: Card) -> str:
    """Turn a card title into something that reads naturally mid-sentence."""
    terms = card.key_terms or []
    if terms:
        return str(terms[0].get("term", "")).strip() or card.title.rstrip("?")
    return card.title.rstrip("?").lower()


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


async def send_to_profile(
    session: AsyncSession, profile: Profile, notification: Notification
) -> int:
    """Push to every device this reader has registered. Returns delivery count."""
    if not settings.push_enabled:
        logger.info("push disabled (no VAPID keys); would have sent: %s", notification.title)
        return 0

    subscriptions = list(
        (
            await session.execute(
                select(PushSubscription).where(PushSubscription.profile_id == profile.id)
            )
        ).scalars()
    )

    delivered = 0
    for subscription in subscriptions:
        ok = await _send_one(session, subscription, notification)
        delivered += int(ok)
    return delivered


async def _send_one(
    session: AsyncSession, subscription: PushSubscription, notification: Notification
) -> bool:
    info = {
        "endpoint": subscription.endpoint,
        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
    }
    try:
        # pywebpush is synchronous; keep it off the event loop.
        await asyncio.to_thread(
            webpush,
            subscription_info=info,
            data=notification.payload(),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=86400,
        )
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            # The browser has permanently discarded this endpoint.
            await session.delete(subscription)
            logger.info("removed expired push subscription")
            return False
        subscription.failure_count += 1
        if subscription.failure_count >= MAX_FAILURES:
            await session.delete(subscription)
        logger.warning("push failed (%s): %s", status, exc)
        return False

    subscription.failure_count = 0
    subscription.last_sent_at = datetime.now(timezone.utc)
    return True


async def send_daily_round(session: AsyncSession, *, hour_utc: int | None = None) -> dict:
    """Called hourly by the scheduler; delivers to whoever opted into this hour."""
    hour = hour_utc if hour_utc is not None else datetime.now(timezone.utc).hour

    profiles = list(
        (
            await session.execute(
                select(Profile).where(
                    Profile.notify_daily.is_(True), Profile.notify_hour_utc == hour
                )
            )
        ).scalars()
    )

    sent = 0
    skipped = 0
    for profile in profiles:
        if await _already_notified_today(session, profile):
            skipped += 1
            continue
        notification = await compose_for(session, profile)
        if notification is None:
            skipped += 1
            continue
        sent += await send_to_profile(session, profile, notification)

    await session.commit()
    return {"hour_utc": hour, "candidates": len(profiles), "sent": sent, "skipped": skipped}


async def _already_notified_today(session: AsyncSession, profile: Profile) -> bool:
    """One notification per day, enforced server-side rather than by good intentions."""
    since = datetime.now(timezone.utc) - timedelta(hours=20)
    recent = await session.scalar(
        select(PushSubscription)
        .where(
            PushSubscription.profile_id == profile.id,
            PushSubscription.last_sent_at.is_not(None),
            PushSubscription.last_sent_at >= since,
        )
        .limit(1)
    )
    return recent is not None
