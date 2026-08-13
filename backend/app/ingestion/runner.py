"""The discovery run: forums in, published cards out.

One run does the whole loop — collect, merge, triage, synthesise — but stays
deliberately small. `ingestion_max_new_cards_per_run` caps how many cards a
single run will write, because a run that produces forty mediocre cards is
worse for the platform than one that produces three good ones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import pipeline
from app.ai.llm import LLMQuotaExceeded, LLMUnavailable, llm
from app.core.config import settings
from app.ingestion import dedupe
from app.ingestion.sources import forums
from app.ingestion import triage
from app.models import Question
from app.services import discovery

logger = logging.getLogger(__name__)


@dataclass
class RunReport:
    collected: int = 0
    new_questions: int = 0
    merged: int = 0
    triaged_keep: int = 0
    cards_created: int = 0
    cards_failed: int = 0
    skipped_reason: str = ""
    created_slugs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "collected": self.collected,
            "new_questions": self.new_questions,
            "merged": self.merged,
            "triaged_keep": self.triaged_keep,
            "cards_created": self.cards_created,
            "cards_failed": self.cards_failed,
            "skipped_reason": self.skipped_reason,
            "created_slugs": self.created_slugs,
        }


async def discover(session: AsyncSession, *, limit_per_source: int = 40) -> RunReport:
    """Stages 1-2: collect raw questions and merge them into the question pool."""
    report = RunReport()
    discovered = await forums.collect_all(
        limit_per_source=limit_per_source, session=session
    )
    report.collected = len(discovered)

    for item in discovered:
        try:
            _, created = await dedupe.record_observation(session, item)
        except Exception as exc:
            logger.debug("could not record %r: %s", item.raw_text[:60], exc)
            continue
        if created:
            report.new_questions += 1
        else:
            report.merged += 1

    await session.commit()

    # Structural rejection before anything expensive touches the pool.
    await triage.run(session)

    logger.info(
        "discovery: %d collected, %d new, %d merged",
        report.collected,
        report.new_questions,
        report.merged,
    )
    return report


# Words that suggest a question's answer has consequences. Matched against raw
# question text, which is why these are stems rather than the exact tag
# vocabulary in services/discovery.py — nobody asks a question containing the
# word "first-aid", they ask what to do about a burn.
PRACTICAL_HINTS: tuple[str, ...] = (
    "safe", "safety", "danger", "dangerous", "fire", "burn", "poison", "toxic",
    "first aid", "emergency", "survive", "overdose", "choking",
    "scam", "fraud", "phishing", "password", "privacy", "secure", "security",
    "hacked", "stolen", "encrypt",
    "money", "cost", "cheaper", "expensive", "save", "savings", "insurance",
    "tax", "interest rate", "debt",
    "maintain", "maintenance", "repair", "clean", "storage", "store", "last longer",
    "wear out", "warranty",
    "health", "healthy", "medicine", "medical", "doctor", "sleep", "diet",
)


def _practical_rank(text: str) -> int:
    """How many practical hints a question's text mentions. Higher sorts first."""
    lowered = (text or "").lower()
    return sum(1 for hint in PRACTICAL_HINTS if hint in lowered)


# Tags added to a card synthesised from a jurisdiction-bound source. Shelving
# is derived from tags rather than stored (see services/discovery.py), so
# tagging is all that is needed for these to reach the practical shelves.
_PRACTICAL_TAGS: tuple[str, ...] = ("kazakhstan", "cis", "practical")


def _mark_if_practical(question: Question, card) -> None:
    """Mark a card whose answer is bound to one jurisdiction and one moment.

    These cards are worth having and are not durable in the way the rest of
    the corpus is: a rule changes and the answer is wrong, with nothing in the
    text to signal it. So the card says when it was written and against which
    country's rules, and `verified_at` gives the re-check a date to work from.
    """
    if question.source_name not in triage.PRACTICAL_SOURCES:
        return

    card.tags = sorted({*(card.tags or []), *_PRACTICAL_TAGS})
    # Only the tag-derived domains are recomputed, not the full shelf set:
    # `shelves_for_card` reads `card.category`, and touching that lazy
    # relationship here would fire a synchronous load inside the async session.
    card.shelves = sorted({*(card.shelves or []), *discovery.domains_for(card.tags)})
    card.verified_at = datetime.now(timezone.utc)

    caveat = (
        "Answers Kazakhstan/CIS rules as they stood on "
        f"{datetime.now(timezone.utc):%Y-%m-%d}; verify before relying on it."
    )
    existing = (card.confidence_reason or "").strip()
    card.confidence_reason = f"{existing} {caveat}".strip() if existing else caveat


async def synthesize_pending(
    session: AsyncSession,
    *,
    max_cards: int | None = None,
    practical_first: bool = False,
) -> RunReport:
    """Stages 3-17: triage the unprocessed pool and write cards for the best."""
    report = RunReport()
    budget = max_cards or settings.ingestion_max_new_cards_per_run

    if not llm.enabled:
        report.skipped_reason = "GEMINI_API_KEY not set — synthesis disabled"
        logger.info("synthesis skipped: no API key")
        return report

    # Candidates: never processed, asked more than once or with real traction.
    rows = await session.execute(
        select(Question)
        .where(Question.processed.is_(False), Question.card_id.is_(None))
        .order_by(Question.occurrences.desc(), Question.engagement.desc())
        .limit(budget * 6)
    )
    candidates = list(rows.scalars())
    if not candidates:
        report.skipped_reason = "no unprocessed questions"
        return report

    try:
        verdicts = await pipeline.triage_questions(candidates)
    except LLMQuotaExceeded as exc:
        report.skipped_reason = str(exc)
        logger.warning("triage stopped: %s", exc)
        return report

    keepers = [
        (question, verdicts[question.id])
        for question in candidates
        if verdicts.get(question.id, {}).get("keep")
    ]
    if practical_first:
        # Stocking useful mode. Curiosity still breaks ties, so this reorders
        # the batch rather than lowering the bar — a question the model already
        # rejected does not come back because it mentions money.
        keepers.sort(
            key=lambda pair: (
                _practical_rank(pair[1].get("canonical_question") or pair[0].raw_text),
                pair[1].get("curiosity_score", 0),
            ),
            reverse=True,
        )
    else:
        keepers.sort(key=lambda pair: pair[1].get("curiosity_score", 0), reverse=True)
    report.triaged_keep = len(keepers)

    # Mark everything the model rejected so it is never reconsidered.
    for question in candidates:
        verdict = verdicts.get(question.id)
        if verdict and not verdict.get("keep"):
            question.processed = True
            question.rejected_reason = str(verdict.get("reason", "not durable"))[:200]
    await session.commit()

    for question, verdict in keepers[:budget]:
        canonical = str(verdict.get("canonical_question") or question.raw_text)
        observed = await dedupe.curiosity_score(question)
        model_score = float(verdict.get("curiosity_score") or 0)
        # Blend what we measured with what the model judges: a question asked
        # once can still be one everybody eventually wonders.
        curiosity = round(max(observed, 0.5 * observed + 0.5 * model_score), 4)

        try:
            variants = await dedupe.variants_of(session, question)
            result = await pipeline.synthesize(
                session,
                canonical,
                also_asked_as=variants,
                curiosity=curiosity,
                origin="ingested",
            )
        except LLMQuotaExceeded as exc:
            # The rest of the batch cannot succeed either — stop rather than
            # generating a string of identical failures against a dead quota.
            await session.rollback()
            report.skipped_reason = str(exc)
            logger.warning("batch stopped after %d card(s): %s", report.cards_created, exc)
            break
        except (LLMUnavailable, ValueError) as exc:
            logger.warning("synthesis failed for %r: %s", canonical[:70], exc)
            report.cards_failed += 1
            await session.rollback()
            continue

        question.processed = True
        question.card_id = result.card.id
        _mark_if_practical(question, result.card)
        await session.commit()

        report.cards_created += 1
        report.created_slugs.append(result.card.slug)
        logger.info(
            "synthesised %r (confidence %.2f, published=%s)",
            result.card.slug,
            result.confidence,
            result.published,
        )

    return report


async def full_run(
    session: AsyncSession,
    *,
    max_cards: int | None = None,
    practical_first: bool = False,
) -> RunReport:
    """Discovery followed by synthesis — what the scheduler calls."""
    discovery_report = await discover(session)
    synthesis_report = await synthesize_pending(
        session, max_cards=max_cards, practical_first=practical_first
    )

    return RunReport(
        collected=discovery_report.collected,
        new_questions=discovery_report.new_questions,
        merged=discovery_report.merged,
        triaged_keep=synthesis_report.triaged_keep,
        cards_created=synthesis_report.cards_created,
        cards_failed=synthesis_report.cards_failed,
        skipped_reason=synthesis_report.skipped_reason,
        created_slugs=synthesis_report.created_slugs,
    )
