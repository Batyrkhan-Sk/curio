"""Background jobs: discovery runs and the daily notification round."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.db import SessionLocal

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


async def _ingestion_job() -> None:
    from app.ingestion import runner

    async with SessionLocal() as session:
        try:
            report = await runner.full_run(session)
            logger.info("scheduled ingestion: %s", report.as_dict())
        except Exception as exc:
            logger.exception("scheduled ingestion failed: %s", exc)


async def _notification_job() -> None:
    from app.services import push

    async with SessionLocal() as session:
        try:
            result = await push.send_daily_round(session)
            if result["sent"]:
                logger.info("notifications: %s", result)
        except Exception as exc:
            logger.exception("notification round failed: %s", exc)


async def _embedding_job() -> None:
    from app.services import embeddings

    async with SessionLocal() as session:
        try:
            cards = await embeddings.backfill_card_embeddings(session)
            concepts = await embeddings.backfill_concept_embeddings(session)
            if cards or concepts:
                logger.info("embedded %d cards, %d concepts", cards, concepts)
        except Exception as exc:
            logger.exception("embedding backfill failed: %s", exc)


def start() -> None:
    if scheduler.running:
        return

    if settings.ingestion_enabled:
        scheduler.add_job(
            _ingestion_job,
            IntervalTrigger(minutes=settings.ingestion_interval_minutes),
            id="ingestion",
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "ingestion scheduled every %d minutes", settings.ingestion_interval_minutes
        )

    # Hourly, so readers in every timezone get their chosen hour. The job
    # itself only sends to profiles whose notify_hour matches.
    scheduler.add_job(
        _notification_job,
        CronTrigger(minute=0),
        id="notifications",
        max_instances=1,
        coalesce=True,
    )

    if settings.gemini_api_key:  # embeddings are Gemini-only
        scheduler.add_job(
            _embedding_job,
            IntervalTrigger(minutes=15),
            id="embeddings",
            max_instances=1,
            coalesce=True,
        )

    scheduler.start()
    logger.info("scheduler started with %d job(s)", len(scheduler.get_jobs()))


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
