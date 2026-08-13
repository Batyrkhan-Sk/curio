"""AI endpoints: re-explanation, and on-demand synthesis."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.ai import pipeline, reexplain as reexplain_service
from app.ai.llm import LLMQuotaExceeded, LLMUnavailable, llm
from app.api.deps import DbSession, OptionalProfile, not_found
from app.core.db import SessionLocal
from app.models import Card
from app.schemas.profile import ReexplainIn, ReexplainOut
from app.services import personalization

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status")
async def ai_status() -> dict:
    """So the UI can explain honestly which features are switched off."""
    return {
        "llm_enabled": llm.enabled,
        "model": llm.model,
        "providers": llm.describe(),
        "features": {
            "reexplain": True,  # falls back to unseen levels without a key
            "reexplain_generative": llm.enabled,
            # Semantic search needs embeddings specifically, which do not fail
            # over between providers.
            "semantic_search": llm.embeddings_available,
            "synthesis": llm.enabled,
            "ingestion": llm.enabled,
        },
    }


@router.post("/cards/{slug}/reexplain", response_model=ReexplainOut)
async def reexplain(
    slug: str,
    body: ReexplainIn,
    session: DbSession,
    profile: OptionalProfile,
) -> ReexplainOut:
    """"I still don't understand." Never returns the same shape twice."""
    card = await session.scalar(
        select(Card).options(selectinload(Card.category)).where(Card.slug == slug)
    )
    if card is None:
        raise not_found()

    try:
        result = await reexplain_service.reexplain(
            card,
            tried=body.tried,
            last_response=body.last_response,
            mode=body.mode,
        )
    except LLMQuotaExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    except LLMUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if profile is not None:
        await personalization.record_interaction(
            session, profile, card, kind="asked_again"
        )
        await session.commit()

    return ReexplainOut(
        mode=result["mode"],
        label=result["label"],
        body=result["body"],
        generated=result.get("generated") == "true",
        tried=[*body.tried, result["mode"]],
    )


class SynthesizeIn(BaseModel):
    question: str = Field(min_length=8, max_length=300)
    background: bool = True


@router.post("/synthesize", status_code=status.HTTP_202_ACCEPTED)
async def synthesize(
    body: SynthesizeIn,
    background: BackgroundTasks,
    session: DbSession,
) -> dict:
    """Ask the platform to research and write a card for a question.

    Synthesis takes 30-90 seconds end to end (retrieval, generation, then
    verification), so the default is to run it in the background and let the
    client poll for the slug.
    """
    if not llm.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Synthesis needs GEMINI_API_KEY. Curated content is still available.",
        )

    from slugify import slugify

    slug = slugify(body.question)[:220]
    existing = await session.scalar(select(Card).where(Card.slug == slug))
    if existing is not None:
        return {"status": "exists", "slug": existing.slug}

    if body.background:
        background.add_task(_synthesize_detached, body.question)
        return {"status": "queued", "slug": slug, "poll": f"/api/v1/cards/{slug}"}

    result = await pipeline.synthesize(session, body.question, origin="manual")
    return {
        "status": "done",
        "slug": result.card.slug,
        "published": result.published,
        "confidence": result.confidence,
        "notes": result.notes,
    }


async def _synthesize_detached(question: str) -> None:
    """Background synthesis needs its own session; the request's is long gone."""
    async with SessionLocal() as session:
        try:
            result = await pipeline.synthesize(session, question, origin="manual")
            logger.info(
                "on-demand synthesis complete: %s (published=%s)",
                result.card.slug,
                result.published,
            )
        except Exception as exc:
            logger.exception("on-demand synthesis failed for %r: %s", question[:80], exc)
