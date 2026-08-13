"""Learning what a reader is interested in — without closing the world down.

The explicit design constraint from the brief is no echo chambers. Two
mechanisms enforce it:

* `serendipity` is a floor, not a decay target. A fixed share of every
  recommendation set is drawn from categories the reader has *not* engaged
  with, and the floor can never reach zero.
* Interest weights decay over time, so a week spent reading about aviation
  does not define someone permanently.
"""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Card, CardConcept, Category, Concept, Interaction, Profile

logger = logging.getLogger(__name__)

INTEREST_DECAY = 0.97
"""Applied per recorded interaction. Roughly halves an untouched interest
after ~25 further interactions elsewhere."""

INTEREST_GAIN = {
    "view": 0.04,
    "complete": 0.12,
    "save": 0.15,
    "level_reached": 0.03,
    "dismissed": -0.10,
    "unsave": -0.05,
}

MIN_SERENDIPITY = 0.15


async def get_or_create_profile(session: AsyncSession, key: str | None) -> Profile:
    """Resolve the anonymous profile key, minting one if the client has none."""
    if key:
        profile = await session.scalar(select(Profile).where(Profile.key == key))
        if profile is not None:
            return profile

    profile = Profile(key=key or secrets.token_urlsafe(24))
    session.add(profile)
    await session.flush()
    return profile


async def record_interaction(
    session: AsyncSession,
    profile: Profile,
    card: Card,
    *,
    kind: str,
    level: int = 0,
    seconds: int = 0,
) -> None:
    session.add(
        Interaction(
            profile_id=profile.id,
            card_id=card.id,
            kind=kind,
            level=level,
            seconds=seconds,
        )
    )

    if kind == "save":
        card.save_count += 1
    elif kind == "unsave":
        card.save_count = max(0, card.save_count - 1)

    _update_interests(profile, card, kind)
    _update_known_concepts(profile, card, kind, level)
    _update_streak(profile)


def _update_interests(profile: Profile, card: Card, kind: str) -> None:
    gain = INTEREST_GAIN.get(kind)
    if gain is None or card.category is None:
        return

    interests = dict(profile.interests or {})
    for slug in interests:
        interests[slug] = round(interests[slug] * INTEREST_DECAY, 4)

    slug = card.category.slug
    interests[slug] = round(max(0.0, min(1.0, interests.get(slug, 0.0) + gain)), 4)
    profile.interests = {k: v for k, v in interests.items() if v > 0.01}


def _update_known_concepts(profile: Profile, card: Card, kind: str, level: int) -> None:
    """Track familiarity so explanations can start where the reader already is."""
    if kind not in {"complete", "level_reached", "view"}:
        return

    known = dict(profile.known_concepts or {})
    # Reaching level 4 signals far more understanding than opening the page.
    strength = {"view": 0.05, "level_reached": 0.06 * max(1, level), "complete": 0.35}[kind]

    for term in (card.key_terms or [])[:10]:
        name = str(term.get("term", "")).strip().lower()
        if not name:
            continue
        known[name] = round(min(1.0, known.get(name, 0.0) + strength), 4)
    profile.known_concepts = known

    if kind == "level_reached" and level > profile.preferred_level:
        # The reader keeps going deeper; meet them there next time.
        profile.preferred_level = min(5, level)


def _update_streak(profile: Profile) -> None:
    today = datetime.now(timezone.utc).date()
    last = profile.last_active_on

    if last == today:
        return
    if last == today - timedelta(days=1):
        profile.streak_days += 1
    else:
        profile.streak_days = 1

    profile.longest_streak = max(profile.longest_streak, profile.streak_days)
    profile.last_active_on = today


async def recommend(
    session: AsyncSession,
    profile: Profile,
    *,
    limit: int = 12,
) -> list[Card]:
    """Cards this reader would probably enjoy, plus a deliberate share they
    would never have found."""
    seen_ids = set(
        (
            await session.execute(
                select(Interaction.card_id).where(Interaction.profile_id == profile.id)
            )
        ).scalars()
    )

    serendipity = max(MIN_SERENDIPITY, profile.serendipity)
    familiar_count = max(1, round(limit * (1 - serendipity)))
    novel_count = max(1, limit - familiar_count)

    interests = profile.interests or {}
    top_categories = sorted(interests, key=lambda k: interests[k], reverse=True)[:4]

    familiar: list[Card] = []
    if top_categories:
        rows = await session.execute(
            select(Card)
            .options(selectinload(Card.category))
            .join(Category, Card.category_id == Category.id)
            .where(
                Card.status == "published",
                Category.slug.in_(top_categories),
                Card.id.notin_(seen_ids) if seen_ids else True,
            )
            .order_by(Card.curiosity_score.desc(), Card.confidence.desc())
            .limit(familiar_count * 2)
        )
        familiar = list(rows.scalars().unique())[:familiar_count]

    # The novel half explicitly excludes everything the reader already leans
    # towards. This is the anti-echo-chamber mechanism, and it is not optional.
    novel_rows = await session.execute(
        select(Card)
        .options(selectinload(Card.category))
        .join(Category, Card.category_id == Category.id)
        .where(
            Card.status == "published",
            Category.slug.notin_(top_categories) if top_categories else True,
            Card.id.notin_(seen_ids) if seen_ids else True,
            Card.confidence >= 0.6,
        )
        .order_by(func.random())
        .limit(novel_count * 2)
    )
    novel = list(novel_rows.scalars().unique())[:novel_count]

    combined = familiar + novel
    if len(combined) < limit:
        filler = await session.execute(
            select(Card)
            .options(selectinload(Card.category))
            .where(
                Card.status == "published",
                Card.id.notin_([c.id for c in combined] + list(seen_ids))
                if (combined or seen_ids)
                else True,
            )
            .order_by(func.random())
            .limit(limit - len(combined))
        )
        combined.extend(filler.scalars().unique())

    return combined[:limit]


async def next_in_learning_path(
    session: AsyncSession, profile: Profile, card: Card, *, limit: int = 3
) -> list[Card]:
    """What to read after this one, given what the reader already understands.

    Prefers cards that share a concept with the current one but introduce at
    least one new concept — the definition of a step forward rather than
    sideways.
    """
    known = set((profile.known_concepts or {}).keys())

    concept_ids = list(
        (
            await session.execute(
                select(CardConcept.concept_id).where(CardConcept.card_id == card.id)
            )
        ).scalars()
    )
    if not concept_ids:
        return []

    rows = await session.execute(
        select(Card)
        .options(selectinload(Card.category))
        .join(CardConcept, CardConcept.card_id == Card.id)
        .where(
            CardConcept.concept_id.in_(concept_ids),
            Card.id != card.id,
            Card.status == "published",
        )
        .distinct()
        .limit(limit * 4)
    )

    scored: list[tuple[float, Card]] = []
    for candidate in rows.scalars().unique():
        terms = {str(t.get("term", "")).lower() for t in (candidate.key_terms or [])}
        if not terms:
            continue
        new_terms = terms - known
        # Sweet spot: mostly familiar, with something genuinely new in it.
        novelty = len(new_terms) / len(terms)
        score = 1.0 - abs(novelty - 0.4)
        scored.append((score, candidate))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [card for _, card in scored[:limit]]


async def stats(session: AsyncSession, profile: Profile) -> dict:
    """The gamification numbers — counts of real learning, not points."""
    counts = dict(
        (
            await session.execute(
                select(Interaction.kind, func.count(Interaction.id))
                .where(Interaction.profile_id == profile.id)
                .group_by(Interaction.kind)
            )
        ).all()
    )

    seconds = await session.scalar(
        select(func.coalesce(func.sum(Interaction.seconds), 0)).where(
            Interaction.profile_id == profile.id
        )
    )

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    this_week = await session.scalar(
        select(func.count(func.distinct(Interaction.card_id))).where(
            Interaction.profile_id == profile.id,
            Interaction.created_at >= week_ago,
        )
    )

    concepts_explored = await session.scalar(
        select(func.count(func.distinct(CardConcept.concept_id)))
        .select_from(Interaction)
        .join(CardConcept, CardConcept.card_id == Interaction.card_id)
        .where(Interaction.profile_id == profile.id)
    )

    interests = profile.interests or {}
    top = sorted(interests.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "cards_read": int(counts.get("view", 0)),
        "cards_saved": max(0, int(counts.get("save", 0)) - int(counts.get("unsave", 0))),
        "cards_completed": int(counts.get("complete", 0)),
        "concepts_explored": int(concepts_explored or 0),
        "connections_followed": int(counts.get("level_reached", 0)),
        "minutes_learning": int((seconds or 0) // 60),
        "streak_days": profile.streak_days,
        "longest_streak": profile.longest_streak,
        "discoveries_this_week": int(this_week or 0),
        "top_categories": [{"slug": slug, "affinity": value} for slug, value in top],
    }


async def saved_cards(session: AsyncSession, profile: Profile) -> list[Card]:
    """Currently-saved cards: every save that has not been undone since."""
    rows = await session.execute(
        select(Interaction.card_id, Interaction.kind, Interaction.created_at)
        .where(
            Interaction.profile_id == profile.id,
            Interaction.kind.in_(["save", "unsave"]),
        )
        .order_by(Interaction.created_at.asc())
    )

    state: dict = {}
    for card_id, kind, _ in rows:
        state[card_id] = kind == "save"

    active = [card_id for card_id, is_saved in state.items() if is_saved]
    if not active:
        return []

    cards = await session.execute(
        select(Card).options(selectinload(Card.category)).where(Card.id.in_(active))
    )
    return list(cards.scalars().unique())


async def unexplored_category(session: AsyncSession, profile: Profile) -> Category | None:
    """A category this reader has never touched — used by notifications."""
    touched = set((profile.interests or {}).keys())
    rows = await session.execute(
        select(Category)
        .where(Category.slug.notin_(touched) if touched else True)
        .order_by(func.random())
        .limit(1)
    )
    return rows.scalar_one_or_none()


def today() -> date:
    return datetime.now(timezone.utc).date()
