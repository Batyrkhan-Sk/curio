"""Async SQLAlchemy engine, session factory, and schema bootstrap."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """Create the pgvector extension, tables, and the vector indexes.

    Alembic lives in `alembic/` for production migrations; this path keeps
    `docker compose up` a single command in development.
    """
    from app.models import Base  # imported late so all models are registered

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)

        # IVFFlat needs data to train on; HNSW does not, so it is the better
        # fit for a corpus that grows continuously via ingestion.
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS cards_embedding_idx ON cards "
                "USING hnsw (embedding vector_cosine_ops)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS concepts_embedding_idx ON concepts "
                "USING hnsw (embedding vector_cosine_ops)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS questions_text_trgm_idx ON questions "
                "USING gin (normalized_text gin_trgm_ops)"
            )
        )

        # `create_all` adds missing tables but never missing columns, so a
        # column introduced after a table exists in someone's database would
        # never appear. Postgres makes the fix idempotent; each of these is
        # safe to run on every boot and is a no-op once applied.
        for statement in (
            "ALTER TABLE telegram_links ADD COLUMN IF NOT EXISTS locale VARCHAR(8) DEFAULT ''",
            "ALTER TABLE telegram_links ADD COLUMN IF NOT EXISTS mode VARCHAR(16) DEFAULT ''",
            "ALTER TABLE questions ADD COLUMN IF NOT EXISTS original_text TEXT DEFAULT ''",
            "ALTER TABLE questions ADD COLUMN IF NOT EXISTS original_language VARCHAR(8) DEFAULT ''",
            "ALTER TABLE questions ADD COLUMN IF NOT EXISTS image JSONB DEFAULT '{}'::jsonb",
            "ALTER TABLE cards ADD COLUMN IF NOT EXISTS image JSONB DEFAULT '{}'::jsonb",
        ):
            await conn.execute(text(statement))
