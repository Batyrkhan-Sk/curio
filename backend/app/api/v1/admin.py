"""Operational endpoints: trigger ingestion, reindex, reseed.

Unauthenticated by design in development. Put these behind your ingress auth
or drop the router before exposing the API publicly.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks

from app.api.deps import DbSession
from app.core.db import SessionLocal
from app.ingestion import runner, triage
from app.services import embeddings, push
from app.services import search as search_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/ingest")
async def ingest(background: BackgroundTasks, discover_only: bool = False) -> dict:
    """Kick off a discovery run. Returns immediately; check the logs."""
    background.add_task(_run_ingestion, discover_only)
    return {"status": "started", "discover_only": discover_only}


async def _run_ingestion(discover_only: bool) -> None:
    async with SessionLocal() as session:
        try:
            report = (
                await runner.discover(session)
                if discover_only
                else await runner.full_run(session)
            )
            logger.info("ingestion run finished: %s", report.as_dict())
        except Exception as exc:
            logger.exception("ingestion run failed: %s", exc)


@router.post("/ingest/sync")
async def ingest_sync(session: DbSession, discover_only: bool = True) -> dict:
    """Run ingestion inline and return the report — useful when debugging."""
    report = (
        await runner.discover(session) if discover_only else await runner.full_run(session)
    )
    return report.as_dict()


@router.post("/synthesize")
async def synthesize_batch(session: DbSession, count: int = 3) -> dict:
    """Write cards for the best pending questions. Runs inline; slow by nature."""
    report = await runner.synthesize_pending(session, max_cards=count)
    return report.as_dict()


@router.post("/triage")
async def heuristic_triage(session: DbSession) -> dict:
    """Reject structurally unsuitable questions. Needs no AI key."""
    return await triage.run(session)


@router.post("/reindex")
async def reindex(session: DbSession) -> dict:
    await search_service.ensure_index()
    count = await search_service.reindex_all(session)
    return {"indexed": count}


@router.post("/embeddings/backfill")
async def backfill(session: DbSession) -> dict:
    cards = await embeddings.backfill_card_embeddings(session)
    concepts = await embeddings.backfill_concept_embeddings(session)
    return {"cards_embedded": cards, "concepts_embedded": concepts}


@router.post("/seed")
async def reseed(session: DbSession, force: bool = False) -> dict:
    from app.db.seed import seed_all

    return await seed_all(session, force=force)


@router.post("/notifications/run")
async def run_notifications(session: DbSession, hour_utc: int | None = None) -> dict:
    return await push.send_daily_round(session, hour_utc=hour_utc)
