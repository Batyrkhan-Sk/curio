"""Questions, knowledge cards, and their sources.

A *question* is a raw observation: somebody, somewhere, asked this. Many
questions collapse into one *card* — the canonical, synthesised answer. That
collapse is the whole point of the platform: it indexes curiosity, not pages.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.models.base import Base, TimestampMixin, UUIDMixin


class Category(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "categories"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(64), default="Sparkles")
    accent: Mapped[str] = mapped_column(String(16), default="#6366f1")
    sort_order: Mapped[int] = mapped_column(Integer, default=100)

    cards: Mapped[list["Card"]] = relationship(back_populates="category")


class Card(Base, UUIDMixin, TimestampMixin):
    """A single unit of understanding, keyed by the question it answers."""

    __tablename__ = "cards"

    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    """The canonical phrasing of the question, e.g. 'Why are airplane windows round?'"""

    one_sentence_answer: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[Category | None] = relationship(back_populates="cards")

    # --- Progressive explanation -----------------------------------------
    # Five levels, always in order: intuition -> analogy -> real example ->
    # technical -> expert. Stored as JSONB so a level can gain fields (audio,
    # animation spec, alternate analogies) without a migration.
    levels: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # Plain-language definitions for every term the card introduces. This is
    # what enforces the beginner-first rule: nothing is used before it is said.
    key_terms: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    misconceptions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    why_it_matters: Mapped[str] = mapped_column(Text, default="")
    historical_background: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    diagrams: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    next_steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # --- Trust ------------------------------------------------------------
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    confidence_reason: Mapped[str] = mapped_column(Text, default="")
    contradictions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Discovery --------------------------------------------------------
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    shelves: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    """Which homepage shelves this card belongs to (see services/discovery.py)."""

    curiosity_score: Mapped[float] = mapped_column(Float, default=0.0)
    """How often humanity asks this, normalised 0-1. Drives 'everyone asks'."""

    difficulty: Mapped[str] = mapped_column(String(16), default="beginner")
    reading_minutes: Mapped[int] = mapped_column(Integer, default=5)

    view_count: Mapped[int] = mapped_column(Integer, default=0)
    save_count: Mapped[int] = mapped_column(Integer, default=0)
    trend_score: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    origin: Mapped[str] = mapped_column(String(16), default="curated")
    """'curated' (seeded), 'ingested' (discovered + synthesised), 'manual'."""

    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim))

    sources: Mapped[list["Source"]] = relationship(
        back_populates="card", cascade="all, delete-orphan", lazy="selectin"
    )
    questions: Mapped[list["Question"]] = relationship(back_populates="card")

    __table_args__ = (
        Index("cards_shelves_idx", "shelves", postgresql_using="gin"),
        Index("cards_tags_idx", "tags", postgresql_using="gin"),
        Index("cards_curiosity_idx", "curiosity_score"),
    )


class Source(Base, UUIDMixin, TimestampMixin):
    """A reference the synthesis actually drew on."""

    __tablename__ = "sources"

    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    card: Mapped[Card] = relationship(back_populates="sources")

    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(String(160), default="")
    kind: Mapped[str] = mapped_column(String(32), default="web")
    """wikipedia | paper | docs | forum | book | video | gov | blog | web"""

    reliability: Mapped[float] = mapped_column(Float, default=0.5)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    supports: Mapped[str] = mapped_column(String(16), default="supports")
    """supports | contradicts | context"""


class Translation(Base, UUIDMixin, TimestampMixin):
    """One piece of text, once, in one language.

    Keyed by a hash of the source string rather than by (card, field, index):
    the same sentence recurs across cards, a card's fields get rewritten
    without the translation of the untouched ones going stale, and the cache
    serves anything with a string in it — level bodies, category names, a
    reader's search query — from one table.

    Translations are content, not user data: they are shared by every reader
    who asks for the same language, which is what keeps the model bill
    proportional to the corpus rather than to traffic.
    """

    __tablename__ = "translations"

    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    """SHA-256 of the exact source text. Hashed rather than indexed directly
    because a level body runs past any sane index key length."""

    locale: Mapped[str] = mapped_column(String(8), index=True)
    source_text: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64), default="")

    __table_args__ = (
        UniqueConstraint("source_hash", "locale", name="uq_translation_source_locale"),
    )


class Question(Base, UUIDMixin, TimestampMixin):
    """A raw question observed in the wild, before or after being merged."""

    __tablename__ = "questions"

    raw_text: Mapped[str] = mapped_column(Text)
    """The question in the pipeline's language, English. For a foreign-language
    source this is a translation, and `original_text` is what was said."""

    original_text: Mapped[str] = mapped_column(Text, default="")
    original_language: Mapped[str] = mapped_column(String(8), default="")
    """Empty for English sources. Set when `raw_text` was translated, so the
    card can quote the question in the words it was actually asked in."""

    normalized_text: Mapped[str] = mapped_column(Text, index=True)
    source_name: Mapped[str] = mapped_column(String(64), default="unknown")
    source_url: Mapped[str] = mapped_column(Text, default="")
    external_id: Mapped[str] = mapped_column(String(200), default="")

    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    engagement: Mapped[int] = mapped_column(Integer, default=0)
    """Upvotes/comments/views from the origin platform, used for curiosity scoring."""

    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    card_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cards.id", ondelete="SET NULL"), index=True
    )
    card: Mapped[Card | None] = relationship(back_populates="questions")

    is_duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id", ondelete="SET NULL")
    )
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rejected_reason: Mapped[str] = mapped_column(String(200), default="")

    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim))

    __table_args__ = (
        UniqueConstraint("source_name", "external_id", name="uq_question_source_external"),
    )
