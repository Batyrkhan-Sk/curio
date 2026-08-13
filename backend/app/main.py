"""Curio API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.api.v1.router import api_router
from app.core import scheduler
from app.core.config import settings
from app.core.db import SessionLocal, engine, init_models
from app.services import search as search_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
logger = logging.getLogger("curio")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting %s (%s)", settings.app_name, settings.environment)

    await init_models()
    await search_service.ensure_index()

    if settings.auto_seed:
        from app.db.seed import is_empty, seed_all

        async with SessionLocal() as session:
            if await is_empty(session):
                logger.info("no cards found — seeding the curated corpus")
                await seed_all(session)
            else:
                # Meilisearch has its own volume and can be wiped independently
                # of Postgres, so re-sync on every boot rather than assuming.
                await search_service.reindex_all(session)

    if not settings.llm_enabled:
        logger.warning(
            "GEMINI_API_KEY not set — synthesis, semantic search, and ingestion "
            "are disabled. Browsing, keyword search, the graph, saves, and "
            "notifications all work normally."
        )
    if not settings.push_enabled:
        logger.warning(
            "VAPID keys not set — push notifications disabled. Generate a pair "
            "with: docker compose run --rm api python -m app.cli vapid"
        )
    if settings.telegram_enabled:
        if not settings.telegram_webhook_secret:
            logger.warning(
                "TELEGRAM_BOT_TOKEN is set but TELEGRAM_WEBHOOK_SECRET is not — "
                "the webhook will reject every update. Run: docker compose run "
                "--rm api python -m app.cli telegram setup"
            )
        if not settings.telegram_webapp_ready:
            logger.warning(
                "TELEGRAM_WEBAPP_URL is not an https origin — the chat bot works, "
                "but the Mini App button cannot be offered."
            )

    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()
        await engine.dispose()
        logger.info("shutdown complete")


app = FastAPI(
    title="Curio API",
    description="Indexing human curiosity rather than web pages.",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this the browser cannot read back the profile key we mint.
    expose_headers=["X-Curio-Profile"],
)

app.include_router(api_router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {
        "status": "ok",
        "llm_enabled": settings.llm_enabled,
        "push_enabled": settings.push_enabled,
        "ingestion_enabled": settings.ingestion_enabled,
    }
