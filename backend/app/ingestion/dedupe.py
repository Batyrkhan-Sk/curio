"""Stages 1-2: detect repeated curiosity, and merge duplicate questions.

Three passes, cheapest first:

1. exact match on the normalised text
2. trigram similarity in Postgres (catches rewordings and typos)
3. cosine distance on embeddings (catches "why is the sky blue" vs
   "what makes the sky look blue during the day")

Pass 3 only runs when an LLM key is configured; without it the first two still
merge the majority of real duplicates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.sources.base import DiscoveredQuestion
from app.models import Question
from app.services.embeddings import embed_text

logger = logging.getLogger(__name__)

TRIGRAM_THRESHOLD = 0.55
"""Above this pg_trgm similarity, two question titles are the same question."""

EMBEDDING_THRESHOLD = 0.18
"""Cosine distance below which two questions express the same curiosity.
Tight on purpose: 'why is the sky blue' and 'why are sunsets red' sit around
0.3 and are genuinely different cards."""


async def record_observation(
    session: AsyncSession, discovered: DiscoveredQuestion
) -> tuple[Question, bool]:
    """Store a discovered question, merging it into an existing one if it is a
    restatement. Returns (question, was_newly_created)."""
    normalized = discovered.normalized_text
    now = discovered.observed_at or datetime.now(timezone.utc)

    existing = await _find_duplicate(session, normalized)
    if existing is not None:
        existing.occurrences += 1
        existing.engagement = max(existing.engagement, discovered.engagement)
        existing.last_seen_at = max(existing.last_seen_at or now, now)
        return existing, False

    question = Question(
        raw_text=discovered.raw_text[:2000],
        original_text=(discovered.original_text or "")[:2000],
        original_language=discovered.original_language,
        normalized_text=normalized,
        source_name=discovered.source_name,
        source_url=discovered.source_url,
        external_id=discovered.external_id or normalized[:200],
        engagement=discovered.engagement,
        occurrences=1,
        first_seen_at=now,
        last_seen_at=now,
    )
    question.embedding = await embed_text(discovered.raw_text, task_type="CLUSTERING")
    session.add(question)
    await session.flush()
    return question, True


async def _find_duplicate(session: AsyncSession, normalized: str) -> Question | None:
    exact = await session.scalar(
        select(Question).where(Question.normalized_text == normalized).limit(1)
    )
    if exact is not None:
        return exact

    similarity = func.similarity(Question.normalized_text, normalized)
    fuzzy = await session.execute(
        select(Question, similarity.label("sim"))
        .where(similarity > TRIGRAM_THRESHOLD)
        .order_by(text("sim DESC"))
        .limit(1)
    )
    row = fuzzy.first()
    if row is not None:
        return row[0]

    embedding = await embed_text(normalized, task_type="CLUSTERING")
    if embedding is None:
        return None

    distance = Question.embedding.cosine_distance(embedding).label("distance")
    semantic = await session.execute(
        select(Question, distance)
        .where(Question.embedding.is_not(None))
        .order_by(distance)
        .limit(1)
    )
    row = semantic.first()
    if row is not None and float(row[1]) < EMBEDDING_THRESHOLD:
        return row[0]
    return None


async def curiosity_score(question: Question) -> float:
    """How widely humanity asks this, normalised to 0..1.

    Repetition matters more than raw engagement: a question asked in five
    different places by five different communities is a better card than one
    thread with ten thousand upvotes.
    """
    repetition = min(1.0, (question.occurrences - 1) / 6.0)
    engagement = min(1.0, question.engagement / 3000.0)
    return round(0.65 * repetition + 0.35 * engagement, 4)


async def variants_of(session: AsyncSession, question: Question, *, limit: int = 8) -> list[str]:
    """Other phrasings that merged into this question, for the synthesis prompt."""
    if question.embedding is None:
        return []
    distance = Question.embedding.cosine_distance(question.embedding).label("distance")
    rows = await session.execute(
        select(Question.raw_text, distance)
        .where(Question.id != question.id, Question.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    return [txt for txt, dist in rows if float(dist) < EMBEDDING_THRESHOLD * 2]
