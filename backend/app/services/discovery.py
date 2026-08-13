"""The homepage: shelves of curiosity rather than a ranked list.

Each shelf answers a different reason someone opens the app — "show me
something new", "show me what I should already know", "I have five minutes".
They are queries, not editorial lists, so the homepage keeps working as the
corpus grows.
"""

from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Card, Interaction, Profile

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ShelfSpec:
    key: str
    title: str
    subtitle: str
    limit: int = 8


PRACTICAL_DOMAINS: dict[str, frozenset[str]] = {
    # Ordered by how badly it hurts to learn the answer too late.
    "safety-first": frozenset(
        {"safety", "first-aid", "emergency", "fire", "poisoning", "health"}
    ),
    "not-getting-fooled": frozenset(
        {"scam", "fraud", "phishing", "security", "privacy", "passwords"}
    ),
    "money-sense": frozenset({"money", "savings", "cost", "insurance"}),
    "around-the-house": frozenset({"maintenance", "storage", "tools", "hobbies"}),
    "out-in-the-world": frozenset({"travel", "places", "transportation"}),
}

PRACTICAL_TAGS: frozenset[str] = frozenset(
    # "practical" belongs to no single domain — it is the card that is useful
    # without being about safety, money or anything else in particular.
    {"practical"}
).union(*PRACTICAL_DOMAINS.values())


def domains_for(tags: list[str] | None) -> list[str]:
    """Which practical domains a card's tags place it in. Usually zero or one."""
    lowered = {t.lower() for t in (tags or [])}
    return [key for key, vocab in PRACTICAL_DOMAINS.items() if vocab & lowered]


def is_practical(tags: list[str] | None) -> bool:
    """Whether a card's answer has consequences beyond satisfying curiosity.

    Deliberately keyed off tags rather than a new column: the shelf is derived
    data like every other, so it stays correct as cards are rewritten and needs
    no migration to introduce.

    The vocabulary is kept narrow on purpose. A tag like "energy" reads as
    practical and is in fact used by every second physics card, which is how a
    shelf about saving people money ends up recommending special relativity.
    """
    return bool(PRACTICAL_TAGS & {t.lower() for t in (tags or [])})


CURIOSITY_SHELVES: tuple[ShelfSpec, ...] = (
    ShelfSpec(
        "todays-discoveries",
        "Today's discoveries",
        "Questions the platform found interesting since yesterday",
    ),
    ShelfSpec(
        "everyone-asks",
        "Questions everyone eventually asks",
        "The curiosity that keeps resurfacing, everywhere, for years",
    ),
    ShelfSpec(
        "nobody-explains",
        "Things nobody properly explains",
        "Widely misunderstood, and usually explained badly",
    ),
    ShelfSpec(
        "hidden-engineering",
        "Hidden engineering",
        "The deliberate decisions inside things you use without thinking",
    ),
    ShelfSpec(
        "everyday-science",
        "Everyday science",
        "The physics and biology of an ordinary afternoon",
    ),
    ShelfSpec("ai-picks", "AI picks", "Chosen for how satisfying the answer turns out to be"),
    ShelfSpec("five-minutes", "Learn something in five minutes", "Short, complete, self-contained"),
    ShelfSpec("most-saved", "Most saved", "What other readers keep coming back to"),
    ShelfSpec("trending", "Trending curiosity", "Being read far more than usual this week"),
    ShelfSpec("random", "Random curiosity", "No algorithm, no reason — just something unexpected"),
)

PRACTICAL_SHELVES: tuple[ShelfSpec, ...] = (
    ShelfSpec(
        "worth-knowing",
        "Worth knowing before you need it",
        "Answers that can save you money, time, or a great deal of trouble",
    ),
    ShelfSpec(
        "safety-first",
        "The ones that keep you safe",
        "Fire, poison, first aid — the answers you want already in your head",
    ),
    ShelfSpec(
        "not-getting-fooled",
        "How not to get fooled",
        "Scams, passwords and privacy, explained by how they actually work",
    ),
    ShelfSpec(
        "money-sense",
        "Where the money goes",
        "Prices, savings and small decisions that compound",
    ),
    ShelfSpec(
        "around-the-house",
        "Around the house",
        "Keeping ordinary things working, and knowing when they won't",
    ),
    ShelfSpec(
        "out-in-the-world",
        "Out in the world",
        "Getting there, and what to know once you have",
    ),
    ShelfSpec("five-minutes", "Learn something in five minutes", "Short, complete, self-contained"),
    ShelfSpec("random", "Random curiosity", "No algorithm, no reason — just something unexpected"),
)

# The two lenses a reader can put on the corpus. Interesting is the default —
# it is why most people open the app — but the practical answers were getting
# lost among eleven shelves of pleasant surprise, which is the whole reason
# for the split. Modes share shelf *specs* where they overlap, so a shelf is
# described the same way whichever lens it appears under.
MODES: dict[str, tuple[ShelfSpec, ...]] = {
    "interesting": CURIOSITY_SHELVES,
    "useful": PRACTICAL_SHELVES,
}
DEFAULT_MODE = "interesting"

# Every shelf that exists anywhere, for /discovery/shelf/{key}. Deduplicated by
# key, first definition winning, since the two modes share some shelves.
SHELVES: tuple[ShelfSpec, ...] = tuple(
    {shelf.key: shelf for shelf in (*CURIOSITY_SHELVES, *PRACTICAL_SHELVES)}.values()
)

SHELF_BY_KEY = {shelf.key: shelf for shelf in SHELVES}


HIDDEN_ENGINEERING_CATEGORIES: frozenset[str] = frozenset(
    {
        "engineering", "programming", "internet", "cybersecurity",
        "aviation", "cars", "design", "architecture",
    }
)

EVERYDAY_SCIENCE_CATEGORIES: frozenset[str] = frozenset(
    {"science", "physics", "chemistry", "biology", "psychology", "medicine"}
)


def shelves_for_card(card: Card, *, category_slug: str = "", is_new: bool = False) -> list[str]:
    """The one rule that decides which shelves a card belongs to.

    Derived data, never editorial: the homepage stays populated as the corpus
    grows without anyone tagging by hand, and `cli reshelve` can rebuild every
    card's membership from its own properties after a rule changes.

    Ingestion and the seeder used to carry near-identical copies of this, which
    drifted — the seeder had learned about `medicine` and `architecture` and
    the pipeline had not, so the same card shelved differently depending on
    where it came from. `is_new` is the one difference that was ever intended:
    a card that shipped with the install was not discovered today.
    """
    slug = category_slug or (card.category.slug if card.category else "")
    shelves: list[str] = ["todays-discoveries"] if is_new else []

    if card.curiosity_score >= 0.6:
        shelves.append("everyone-asks")
    if len(card.misconceptions or []) >= 2:
        shelves.append("nobody-explains")
    if card.reading_minutes <= 5:
        shelves.append("five-minutes")
    if slug in HIDDEN_ENGINEERING_CATEGORIES:
        shelves.append("hidden-engineering")
    if slug in EVERYDAY_SCIENCE_CATEGORIES:
        shelves.append("everyday-science")
    if card.confidence >= 0.85 and card.curiosity_score >= 0.6:
        shelves.append("ai-picks")
    if is_practical(card.tags):
        shelves.append("worth-knowing")
    # The practical domains are the shelves of useful mode. A card can sit in
    # more than one — a card about phishing a bank is both.
    shelves.extend(domains_for(card.tags))

    return sorted(set(shelves))


def resolve_mode(mode: str | None) -> str:
    """Anything unrecognised reads as the default rather than an error.

    The mode arrives from a URL, a cookie and a Telegram callback, none of
    which are worth failing a page render over.
    """
    value = (mode or "").strip().lower()
    return value if value in MODES else DEFAULT_MODE


def _base_query(mode: str = DEFAULT_MODE) -> Select:
    stmt = (
        select(Card)
        .options(selectinload(Card.category))
        .where(Card.status == "published")
    )
    if resolve_mode(mode) == "useful":
        # The generic shelves — "five minutes", "random" — belong to both modes
        # but must not reach outside the lens: a random card in useful mode
        # still has to be useful, or the mode means nothing.
        stmt = stmt.where(Card.tags.overlap(sorted(PRACTICAL_TAGS)))
    return stmt


async def shelf_cards(
    session: AsyncSession,
    key: str,
    *,
    limit: int = 8,
    exclude_ids: set[str] | None = None,
    mode: str = DEFAULT_MODE,
) -> list[Card]:
    """Fetch one shelf. Each key gets the ordering that actually suits it."""
    exclude_ids = exclude_ids or set()
    stmt = _base_query(mode)

    if key == "todays-discoveries":
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        stmt = stmt.where(Card.created_at >= cutoff).order_by(Card.created_at.desc())
        rows = await session.execute(stmt.limit(limit))
        cards = list(rows.scalars().unique())
        if len(cards) >= max(3, limit // 2):
            return cards
        # A young corpus has nothing new; fall back to a stable daily rotation
        # so the shelf is never empty on a fresh install.
        return await _daily_rotation(session, limit=limit, mode=mode)

    if key == "everyone-asks":
        stmt = stmt.where(Card.curiosity_score >= 0.45).order_by(Card.curiosity_score.desc())
    elif key == "nobody-explains":
        stmt = stmt.where(
            func.jsonb_array_length(Card.misconceptions) >= 2
        ).order_by(func.jsonb_array_length(Card.misconceptions).desc(), Card.curiosity_score.desc())
    elif key == "five-minutes":
        stmt = stmt.where(Card.reading_minutes <= 5).order_by(
            Card.curiosity_score.desc(), Card.reading_minutes.asc()
        )
    elif key == "most-saved":
        stmt = stmt.where(Card.save_count > 0).order_by(Card.save_count.desc())
    elif key == "trending":
        stmt = stmt.order_by(Card.trend_score.desc(), Card.view_count.desc())
    elif key == "random":
        stmt = stmt.order_by(func.random())
    elif key == "ai-picks":
        stmt = stmt.where(Card.shelves.any("ai-picks")).order_by(
            Card.confidence.desc(), Card.curiosity_score.desc()
        )
    else:
        stmt = stmt.where(Card.shelves.any(key)).order_by(Card.curiosity_score.desc())

    rows = await session.execute(stmt.limit(limit * 2))
    cards = [c for c in rows.scalars().unique() if str(c.id) not in exclude_ids]

    if key == "trending" and not any(c.trend_score for c in cards):
        # Nothing has been read yet — trending is meaningless, so show breadth
        # instead of a duplicate of "most saved".
        cards = await _one_per_category(session, limit=limit, mode=mode)

    return cards[:limit]


async def random_card(
    session: AsyncSession,
    *,
    profile: Profile | None = None,
    mode: str = DEFAULT_MODE,
) -> Card | None:
    """A random card that is not one the reader has just been shown.

    Uniform random over a corpus this size repeats constantly — with twenty
    practical cards, two consecutive draws land on the same one about one time
    in twenty, and it reads as broken rather than random. So the reader's own
    recent views are excluded.

    How many to exclude has to scale with the pool: remembering ten cards out
    of a shelf of twelve would make "another" run out of library. A third of
    the pool, capped, leaves the draw feeling unpredictable while guaranteeing
    it never immediately repeats.
    """
    mode = resolve_mode(mode)
    # count() with no argument, so the count is over the subquery's rows rather
    # than joining `cards` in a second time and multiplying the two.
    pool = int(await session.scalar(
        select(func.count()).select_from(_base_query(mode).subquery())
    ) or 0)
    if not pool:
        return None

    memory = max(1, min(10, pool // 3))
    recent: list[uuid.UUID] = []

    if profile is not None:
        rows = await session.execute(
            select(Interaction.card_id)
            .where(Interaction.profile_id == profile.id, Interaction.kind == "view")
            .order_by(Interaction.created_at.desc())
            .limit(memory * 4)
        )
        # Distinct, newest first: a card read three times in a row should cost
        # one slot of memory, not three.
        for card_id in rows.scalars():
            if card_id not in recent:
                recent.append(card_id)
            if len(recent) >= memory:
                break

    stmt = _base_query(mode).order_by(func.random()).limit(1)
    if recent:
        card = await session.scalar(stmt.where(Card.id.notin_(recent)))
        if card is not None:
            return card
        # Everything in the pool has been seen recently. Fall back to excluding
        # only the last card, so "another" always moves even at the end.
        card = await session.scalar(stmt.where(Card.id != recent[0]))
        if card is not None:
            return card

    return await session.scalar(stmt)


async def _daily_rotation(
    session: AsyncSession, *, limit: int, mode: str = DEFAULT_MODE
) -> list[Card]:
    """A deterministic per-day slice of the corpus.

    Same for everyone on a given day, different tomorrow, and it does not
    require any reading history to exist.
    """
    rows = await session.execute(_base_query(mode))
    cards = sorted(rows.scalars().unique(), key=lambda c: c.slug)
    if not cards:
        return []
    seed = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
    rng = random.Random(seed)
    rng.shuffle(cards)
    return cards[:limit]


async def _one_per_category(
    session: AsyncSession, *, limit: int, mode: str = DEFAULT_MODE
) -> list[Card]:
    rows = await session.execute(_base_query(mode).order_by(Card.curiosity_score.desc()))
    seen: set[str] = set()
    picked: list[Card] = []
    for card in rows.scalars().unique():
        slug = card.category.slug if card.category else ""
        if slug in seen:
            continue
        seen.add(slug)
        picked.append(card)
        if len(picked) >= limit:
            break
    return picked


async def build_feed(
    session: AsyncSession,
    *,
    profile: Profile | None = None,
    per_shelf: int = 8,
    mode: str = DEFAULT_MODE,
) -> list[tuple[ShelfSpec, list[Card]]]:
    """Assemble the whole homepage for one mode.

    Repeating a card across shelves makes the corpus feel smaller than it is,
    so cards are normally used once. But strict no-repeat starves the page on a
    young corpus: with a dozen cards the first two shelves would consume
    everything and the rest would vanish. So the allowance scales with how much
    there is to go round — an empty shelf is a worse outcome than a card
    appearing under two different framings, which is in any case a fair
    description of why it is on both.
    """
    mode = resolve_mode(mode)
    order = _order_for(profile, mode)

    # Useful mode draws from a fraction of the corpus, so its budget has to be
    # measured against that fraction — counting the whole library would let it
    # believe it has room to spare and leave half its shelves empty.
    pool = select(func.count(Card.id)).where(Card.status == "published")
    if mode == "useful":
        pool = pool.where(Card.tags.overlap(sorted(PRACTICAL_TAGS)))
    total = int(await session.scalar(pool) or 0)

    capacity = max(1, len(order) * per_shelf)
    max_appearances = 1 if total >= capacity else max(2, round(capacity / max(total, 1) / 2))

    # Narrow shelves choose first. "Everyday science" can only ever be filled
    # from science cards, while "today's discoveries" will take anything — so
    # letting the broad shelves go first strands the narrow ones empty. This
    # only affects allocation; the page is rendered back in `order`.
    candidate_counts = {
        spec.key: len(await shelf_cards(session, spec.key, limit=per_shelf * 3, mode=mode))
        for spec in order
    }
    allocation_order = sorted(order, key=lambda spec: candidate_counts[spec.key])

    appearances: dict[str, int] = {}
    filled: dict[str, list[Card]] = {}

    for spec in allocation_order:
        # "Random curiosity" ignores the budget in both directions: being
        # surprising matters more there than being novel relative to the page.
        is_random = spec.key == "random"
        exhausted = (
            set()
            if is_random
            else {cid for cid, count in appearances.items() if count >= max_appearances}
        )
        cards = await shelf_cards(
            session, spec.key, limit=per_shelf, exclude_ids=exhausted, mode=mode
        )

        # A shelf with one card reads as a mistake rather than a selection.
        if len(cards) < 2:
            continue

        if not is_random:
            for card in cards:
                appearances[str(card.id)] = appearances.get(str(card.id), 0) + 1

        filled[spec.key] = cards

    return [(spec, filled[spec.key]) for spec in order if spec.key in filled]


def _order_for(profile: Profile | None, mode: str = DEFAULT_MODE) -> list[ShelfSpec]:
    """Put the shelf a returning reader most likely wants nearer the top."""
    shelves = list(MODES[resolve_mode(mode)])
    if profile is None:
        return shelves

    if profile.streak_days >= 3:
        # Regulars have seen the evergreen shelves; lead with what is new.
        # Useful mode has no "new" shelf and stays in its stated order — the
        # point there is that safety comes before curiosity, every visit.
        shelves.sort(key=lambda s: 0 if s.key in {"todays-discoveries", "trending"} else 1)
    return shelves


async def record_view(session: AsyncSession, card: Card) -> None:
    """Count a read and refresh the trend score.

    Trend is views over the last seven days weighted against the all-time
    count, so an old card that suddenly gets attention can still trend.
    """
    card.view_count += 1

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent = await session.scalar(
        select(func.count(Interaction.id)).where(
            Interaction.card_id == card.id,
            Interaction.kind == "view",
            Interaction.created_at >= cutoff,
        )
    )
    recent = int(recent or 0)
    baseline = max(1, card.view_count - recent)
    card.trend_score = round(recent / baseline, 4)
