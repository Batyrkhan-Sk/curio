"""The knowledge graph: concepts, and the edges between concepts and cards.

Two layers of connection exist deliberately:

* concept -> concept  : the conceptual map (CPU cache -> memory -> RAM ...)
* card    -> card     : "related questions", which is what a reader follows

Keeping them separate means a card can be re-synthesised without losing the
conceptual structure that other cards depend on.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.models.base import Base, TimestampMixin, UUIDMixin


class Concept(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "concepts"

    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    plain_definition: Mapped[str] = mapped_column(Text, default="")
    """One beginner-safe sentence. Shown on hover anywhere the term appears."""

    category_slug: Mapped[str] = mapped_column(String(64), default="", index=True)
    depth: Mapped[int] = mapped_column(Float, default=0)
    """Rough prerequisite depth: 0 = everyday, 5 = specialist."""

    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim))

    outgoing: Mapped[list["ConceptEdge"]] = relationship(
        back_populates="source",
        foreign_keys="ConceptEdge.source_id",
        cascade="all, delete-orphan",
    )


class ConceptEdge(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "concept_edges"

    source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(32), default="related")
    """leads_to | requires | part_of | contrasts_with | related"""
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    source: Mapped[Concept] = relationship(foreign_keys=[source_id], back_populates="outgoing")
    target: Mapped[Concept] = relationship(foreign_keys=[target_id])

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation", name="uq_concept_edge"),
    )


class CardConcept(Base, UUIDMixin):
    """Which concepts a card teaches, and how centrally."""

    __tablename__ = "card_concepts"

    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), default="covers")
    """covers | requires | mentions"""
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    __table_args__ = (UniqueConstraint("card_id", "concept_id", "role", name="uq_card_concept"),)


class CardLink(Base, UUIDMixin, TimestampMixin):
    """A "related question" edge between two cards."""

    __tablename__ = "card_links"

    source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(32), default="related")
    """related | prerequisite | deeper | contrast | next"""
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    reason: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation", name="uq_card_link"),
        Index("card_links_target_idx", "target_id"),
    )
