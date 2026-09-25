"""The synthesis pipeline: a question in, a published knowledge card out.

The seventeen stages from the product brief map onto this module as follows:

  1-2   detect repeated curiosity, merge duplicates   -> ingestion/dedupe.py
  3     identify the underlying concept                -> triage_questions()
  4     retrieve multiple reliable sources             -> ingestion/evidence.py
  5-6   compare explanations, detect contradictions    -> verify()
  7     verify facts                                   -> verify()
  8-15  generate answers, levels, analogies, diagrams,
        examples, misconceptions                       -> synthesize()
  16    connect related concepts                       -> services/graph.py
  17    recommend what to learn next                   -> synthesize() + graph

Each stage degrades rather than fails. If verification cannot run, the card is
published with a low confidence score and flagged for review — it is never
published claiming a confidence it did not earn.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from slugify import slugify
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import prompts
from app.ai.llm import LLMQuotaExceeded, LLMUnavailable, llm
from app.ingestion import evidence as evidence_module
from app.ingestion import images as images_module
from app.models import Card, Category, Question, Source
from app.services import discovery as discovery_service
from app.services import graph as graph_service
from app.services import search as search_service
from app.services.embeddings import card_embedding_text, embed_text

logger = logging.getLogger(__name__)

MIN_PUBLISH_CONFIDENCE = 0.45
"""Below this the card is stored as `needs_review` and never shown to readers."""


class PipelineDisabled(RuntimeError):
    """Raised when synthesis is requested with no LLM configured."""


@dataclass(slots=True)
class SynthesisResult:
    card: Card
    confidence: float
    published: bool
    notes: list[str]


# ---------------------------------------------------------------------------
# Stage 3 — identify what is actually worth explaining
# ---------------------------------------------------------------------------


async def triage_questions(questions: list[Question]) -> dict[uuid.UUID, dict[str, Any]]:
    """Decide which raw questions deserve a card, and canonicalise their wording."""
    if not llm.enabled or not questions:
        return {}

    texts = [q.raw_text for q in questions]
    try:
        payload = await llm.generate_json(
            prompts.triage_prompt(texts),
            system=prompts.HOUSE_STYLE,
            schema=prompts.QUESTION_TRIAGE_SCHEMA,
            temperature=0.2,
        )
    except LLMQuotaExceeded:
        # Must not be swallowed: an exhausted quota looks identical to "the
        # model rejected everything" once it becomes an empty dict, and the
        # caller would then mark good questions as considered-and-dropped.
        raise
    except LLMUnavailable as exc:
        logger.warning("triage unavailable: %s", exc)
        return {}

    verdicts: dict[uuid.UUID, dict[str, Any]] = {}
    for item in payload.get("results", []):
        index = item.get("index")
        if not isinstance(index, int) or not 0 <= index < len(questions):
            continue
        verdicts[questions[index].id] = item
    return verdicts


# ---------------------------------------------------------------------------
# Stage 4 — plan the research
# ---------------------------------------------------------------------------

SE_SITES = [
    "physics", "chemistry", "biology", "engineering", "electronics", "aviation",
    "space", "earthscience", "security", "crypto", "softwareengineering",
    "serverfault", "money", "economics", "history", "psychology", "cooking",
    "math", "stats", "medicalsciences", "music", "gardening",
]


async def plan_research(question: str) -> dict[str, list[str]]:
    """Turn a question into the topics an encyclopaedia is actually indexed by."""
    fallback = {"topics": [question], "stackexchange_sites": ["physics"]}
    if not llm.enabled:
        return fallback

    try:
        plan = await llm.generate_json(
            prompts.research_plan_prompt(question, SE_SITES),
            schema=prompts.RESEARCH_PLAN_SCHEMA,
            temperature=0.1,
            max_output_tokens=512,
        )
    except LLMQuotaExceeded:
        raise
    except LLMUnavailable as exc:
        logger.warning("research planning unavailable: %s", exc)
        return fallback

    topics = [str(t).strip() for t in (plan.get("topics") or []) if str(t).strip()]
    sites = [
        str(site).strip()
        for site in (plan.get("stackexchange_sites") or [])
        if str(site).strip() in SE_SITES
    ]
    return {
        "topics": topics[:3] or fallback["topics"],
        "stackexchange_sites": sites[:2] or fallback["stackexchange_sites"],
    }


# ---------------------------------------------------------------------------
# Stages 5-15 — synthesise and verify
# ---------------------------------------------------------------------------


async def synthesize(
    session: AsyncSession,
    question_text: str,
    *,
    also_asked_as: list[str] | None = None,
    curiosity: float = 0.0,
    origin: str = "ingested",
    question_image: dict[str, Any] | None = None,
) -> SynthesisResult:
    """Run the full pipeline for one question and persist the result."""
    if not llm.enabled:
        raise PipelineDisabled(
            "Synthesis requires GEMINI_API_KEY. Without it Curio serves its "
            "curated corpus only."
        )

    notes: list[str] = []

    # Stage 4 — decide what to look up, then retrieve. Planning first is what
    # keeps the sources on-topic; searching an encyclopaedia with the raw
    # question returns near-random articles and the card then fails
    # verification for claims the sources never addressed.
    plan = await plan_research(question_text)
    found = await evidence_module.gather(
        question_text, queries=plan["topics"], sites=plan["stackexchange_sites"]
    )
    if not found:
        notes.append("no external evidence retrieved; card written from model knowledge alone")
    evidence_text = evidence_module.format_for_prompt(found)
    # Searched separately from the evidence, and against the planned topics
    # rather than the question, because an image library is indexed by subject
    # name. Failure here is not worth reporting: it costs the card a picture it
    # was never guaranteed.
    searched_images = await images_module.search(plan["topics"])
    image_candidates = _image_candidates(question_image, found, searched_images)

    # Stages 8-15 — generate
    categories = list(
        (await session.execute(select(Category.slug).order_by(Category.sort_order))).scalars()
    )
    draft = await llm.generate_json(
        prompts.synthesis_prompt(
            question_text,
            evidence=evidence_text,
            categories=categories,
            also_asked_as=also_asked_as or [],
            image_candidates=images_module.describe_for_prompt(image_candidates),
        ),
        system=prompts.HOUSE_STYLE,
        schema=prompts.CARD_SCHEMA,
        temperature=0.45,
    )
    draft = _coerce_draft(draft, fallback_title=question_text)

    # Stages 5-7 — compare, detect contradictions, verify
    confidence, confidence_reason, contradictions, review_notes = await verify(draft, evidence_text)
    notes.extend(review_notes)
    if not found:
        confidence = min(confidence, 0.55)

    card = await _persist(
        session,
        draft,
        found,
        confidence=confidence,
        confidence_reason=confidence_reason,
        contradictions=contradictions,
        curiosity=curiosity,
        origin=origin,
        image_candidates=image_candidates,
    )

    published = card.status == "published"
    if published:
        # Stages 16-17 — connect and recommend
        await connect(session, card, draft.get("related_questions", []))
        await session.commit()
        await search_service.index_cards([card])
    else:
        await session.commit()

    return SynthesisResult(
        card=card, confidence=confidence, published=published, notes=notes
    )


async def verify(
    draft: dict[str, Any], evidence_text: str
) -> tuple[float, str, list[dict[str, Any]], list[str]]:
    """Fact-check a draft against its own evidence."""
    notes: list[str] = []
    try:
        report = await llm.generate_json(
            prompts.verification_prompt(json.dumps(draft, ensure_ascii=False)[:24000], evidence_text),
            system=prompts.HOUSE_STYLE,
            schema=prompts.VERIFY_SCHEMA,
            temperature=0.1,
        )
    except LLMQuotaExceeded:
        raise
    except LLMUnavailable as exc:
        logger.warning("verification unavailable: %s", exc)
        return 0.4, "Could not be verified against sources.", [], ["verification skipped"]

    confidence = float(report.get("confidence", 0.4))
    reason = str(report.get("confidence_reason", "")).strip()
    contradictions = report.get("contradictions") or []

    # Both penalties are capped. They are meant to nudge a borderline card
    # below the publish line, not to let one pedantic verification pass bury a
    # well-sourced one — the score the verifier gave is the primary signal.
    unsupported = report.get("unsupported_claims") or []
    if unsupported:
        confidence -= min(0.15, 0.03 * len(unsupported))
        notes.append(f"{len(unsupported)} unsupported claim(s) flagged")

    jargon = report.get("jargon_violations") or []
    if jargon:
        confidence -= min(0.10, 0.02 * len(jargon))
        notes.append(f"jargon used before explanation: {', '.join(jargon[:5])}")

    confidence = max(0.0, confidence)

    return round(min(1.0, confidence), 3), reason, contradictions, notes


# ---------------------------------------------------------------------------
# Stage 16-17 — connect
# ---------------------------------------------------------------------------


async def connect(
    session: AsyncSession, card: Card, related_questions: list[str] | None = None
) -> None:
    """Wire a new card into the graph.

    Three mechanisms, deliberately overlapping: shared concepts (structural),
    vector similarity (semantic), and title matching against the questions the
    model itself suggested (editorial).
    """
    await graph_service.connect_by_shared_concepts(session, card)
    await graph_service.connect_by_similarity(session, card)

    for question_text in (related_questions or [])[:6]:
        slug = slugify(question_text)[:220]
        target = await session.scalar(select(Card).where(Card.slug == slug))
        if target is not None and target.id != card.id:
            await graph_service.link_cards(
                session,
                card.id,
                target.id,
                relation="related",
                weight=0.9,
                reason="Suggested as a natural next question",
            )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def _persist(
    session: AsyncSession,
    draft: dict[str, Any],
    found_evidence: list[evidence_module.Evidence],
    *,
    confidence: float,
    confidence_reason: str,
    contradictions: list[dict[str, Any]],
    curiosity: float,
    origin: str,
    image_candidates: list[images_module.ImageCandidate] | None = None,
) -> Card:
    title = draft["title"].strip()
    slug = slugify(title)[:220]

    existing = await session.scalar(select(Card).where(Card.slug == slug))
    card = existing or Card(slug=slug)

    category = None
    if draft.get("category_slug"):
        category = await session.scalar(
            select(Category).where(Category.slug == draft["category_slug"])
        )

    card.title = title
    card.one_sentence_answer = draft["one_sentence_answer"].strip()
    card.summary = draft.get("summary", "").strip()
    card.category = category
    card.levels = draft.get("levels", [])
    card.key_terms = draft.get("key_terms", [])
    card.misconceptions = draft.get("misconceptions", [])
    card.why_it_matters = draft.get("why_it_matters", "")
    card.historical_background = draft.get("historical_background", {}) or {}
    card.diagrams = draft.get("diagrams", []) or []
    card.next_steps = draft.get("next_steps", []) or []
    card.image = _chosen_image(draft, image_candidates or [])
    card.tags = [t.lower()[:64] for t in (draft.get("tags") or [])][:12]
    card.difficulty = draft.get("difficulty", "beginner")
    card.reading_minutes = int(draft.get("reading_minutes") or 5)
    card.confidence = confidence
    card.confidence_reason = confidence_reason
    card.contradictions = contradictions
    card.verified_at = datetime.now(timezone.utc)
    card.curiosity_score = curiosity
    card.origin = origin
    card.status = "published" if confidence >= MIN_PUBLISH_CONFIDENCE else "needs_review"
    card.shelves = discovery_service.shelves_for_card(card, is_new=True)

    if existing is None:
        session.add(card)
    await session.flush()

    # Sources are replaced wholesale on re-synthesis; keeping stale references
    # around would misrepresent what the current text is based on.
    await session.execute(delete(Source).where(Source.card_id == card.id))
    for item in found_evidence:
        session.add(Source(card_id=card.id, **item.to_source_row()))

    for concept_spec in draft.get("concepts", [])[:8]:
        name = str(concept_spec.get("name", "")).strip()
        if not name:
            continue
        concept = await graph_service.upsert_concept(
            session,
            name,
            plain_definition=str(concept_spec.get("plain_definition", "")),
            category_slug=card.category.slug if card.category else "",
        )
        await graph_service.link_card_concept(
            session, card.id, concept.id, role=concept_spec.get("role", "covers")
        )

    card.embedding = await embed_text(card_embedding_text(card), task_type="RETRIEVAL_DOCUMENT")
    await session.flush()
    return card


MAX_IMAGE_CANDIDATES = 6
"""The asker's picture, the lead images of the cited articles, and a couple
from each searched library. Past this the list costs more attention than the
choice is worth, and a longer menu makes the model likelier to pick *something*
when the right answer is nothing."""


def _image_candidates(
    question_image: dict[str, Any] | None,
    found: list[evidence_module.Evidence],
    searched: list[images_module.ImageCandidate] | None = None,
) -> list[images_module.ImageCandidate]:
    """Assemble what the model gets to choose between.

    The asker's own picture goes first when there is one. That is ordering, not
    preference — but a question that arrived with a photograph is usually a
    question *about* the photograph, and the one thing worse than a card with a
    decorative image is a card that answers "what is this thing?" while showing
    a different thing.

    Behind it come the lead images of the articles the card actually cites,
    then whatever the image libraries turned up. That order is deliberate too:
    a picture from a source the card already names needs no further
    justification, while a searched one is only related to the subject by a
    string match and has more to prove.
    """
    candidates: list[images_module.ImageCandidate] = []
    seen: set[str] = set()

    for candidate in (
        [images_module.ImageCandidate.from_json(question_image)]
        + [item.image for item in found]
        + list(searched or [])
    ):
        if candidate is None or candidate.url in seen:
            continue
        # Re-checked rather than trusted: the question's image was gated when it
        # was observed, which may have been weeks and a schema change ago.
        if not images_module.usable(candidate):
            continue
        seen.add(candidate.url)
        candidates.append(candidate)

    return candidates[:MAX_IMAGE_CANDIDATES]


def _chosen_image(
    draft: dict[str, Any], candidates: list[images_module.ImageCandidate]
) -> dict[str, Any]:
    """Resolve the model's pick into the row that gets stored.

    Anything unexpected resolves to no image. A card without a picture is the
    normal case and reads perfectly well, so there is never a reason to guess
    at what a malformed answer meant — and guessing would defeat the gate,
    since the failure mode being defended against is a picture appearing on a
    card that should not have one.
    """
    choice = draft.get("image")
    if not isinstance(choice, dict) or not candidates:
        return {}

    try:
        index = int(choice.get("candidate", -1))
    except (TypeError, ValueError):
        return {}
    if not 0 <= index < len(candidates):
        return {}

    picked = candidates[index].to_json()
    picked["caption"] = str(choice.get("caption") or "").strip()[:300]
    picked["alt"] = str(choice.get("alt") or "").strip()[:300] or picked["title"]
    return picked


def _coerce_draft(draft: Any, *, fallback_title: str) -> dict[str, Any]:
    """Defend against a model that returns almost-right JSON."""
    if not isinstance(draft, dict):
        raise ValueError(f"synthesis returned {type(draft).__name__}, expected an object")

    draft.setdefault("title", fallback_title)
    if not str(draft["title"]).strip().endswith("?"):
        draft["title"] = str(draft["title"]).strip().rstrip(".") + "?"
    draft.setdefault("one_sentence_answer", "")
    draft.setdefault("summary", "")

    levels = draft.get("levels") or []
    normalised: list[dict[str, Any]] = []
    for i, level in enumerate(levels[:5], start=1):
        if not isinstance(level, dict):
            continue
        normalised.append(
            {
                "level": int(level.get("level") or i),
                "label": str(level.get("label") or _DEFAULT_LABELS.get(i, f"Level {i}")),
                "body": str(level.get("body") or "").strip(),
            }
        )
    normalised.sort(key=lambda level: level["level"])
    draft["levels"] = [level for level in normalised if level["body"]]

    if not draft["levels"]:
        raise ValueError("synthesis produced no usable explanation levels")
    return draft


_DEFAULT_LABELS = {
    1: "Simple intuition",
    2: "Visual analogy",
    3: "Real-world example",
    4: "Technical explanation",
    5: "Expert details",
}
