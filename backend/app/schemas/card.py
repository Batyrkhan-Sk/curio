"""Response shapes for cards. These are the contract the frontend types mirror."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExplanationLevel(BaseModel):
    level: int
    label: str
    body: str


class KeyTerm(BaseModel):
    term: str
    plain_definition: str = ""


class Misconception(BaseModel):
    myth: str
    reality: str


class Diagram(BaseModel):
    title: str
    kind: str = "mermaid"
    content: str
    caption: str = ""


class CardImage(BaseModel):
    """The one picture on a card, if it has one.

    `url` is Curio's own proxy path rather than the upstream address — see
    `api/v1/media.py`. The credit fields travel with it in the same object so
    that no client can render the picture while forgetting to say whose it is.
    """

    url: str
    alt: str = ""
    caption: str = ""
    credit: str = ""
    license: str = ""
    license_url: str = ""
    source_url: str = ""
    provider: str = ""
    origin: str = "evidence"
    """'question' when the person asking attached it, 'evidence' when a source
    the card cites did. The web card says which, because "here is the photo
    they posted" and "here is a picture of the thing" are different claims."""

    width: int = 0
    height: int = 0


class NextStep(BaseModel):
    label: str
    reason: str = ""


class HistoricalBackground(BaseModel):
    origin: str = ""
    motivation: str = ""
    evolution: str = ""


class Contradiction(BaseModel):
    claim: str
    conflict: str
    resolution: str = ""


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    url: str
    publisher: str = ""
    kind: str = "web"
    reliability: float = 0.5
    excerpt: str = ""


class AskedAt(BaseModel):
    """Where a question was actually observed being asked.

    Present for ingested cards, empty for the curated corpus — which is the
    honest answer for those, since nobody retrieved them from anywhere.
    """

    model_config = ConfigDict(from_attributes=True)

    source_name: str
    source_url: str = ""
    raw_text: str = ""
    original_text: str = ""
    """Set when the question was asked in another language. The card shows this
    rather than the translation, because quoting somebody in words they never
    used is not a citation."""

    original_language: str = ""
    occurrences: int = 1
    engagement: int = 0
    first_seen_at: datetime | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    icon: str = "Sparkles"
    accent: str = "#6366f1"
    description: str = ""


class CardSummary(BaseModel):
    """What a shelf, a search result, or a graph node needs — nothing more."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    one_sentence_answer: str
    summary: str = ""
    category: CategoryOut | None = None
    tags: list[str] = Field(default_factory=list)
    difficulty: str = "beginner"
    reading_minutes: int = 5
    confidence: float = 0.5
    curiosity_score: float = 0.0
    save_count: int = 0
    view_count: int = 0


class RelatedCard(CardSummary):
    relation: str = "related"
    reason: str = ""


class CardDetail(CardSummary):
    levels: list[ExplanationLevel] = Field(default_factory=list)
    key_terms: list[KeyTerm] = Field(default_factory=list)
    misconceptions: list[Misconception] = Field(default_factory=list)
    why_it_matters: str = ""
    historical_background: HistoricalBackground = Field(default_factory=HistoricalBackground)
    diagrams: list[Diagram] = Field(default_factory=list)
    image: CardImage | None = None
    next_steps: list[NextStep] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    confidence_reason: str = ""
    sources: list[SourceOut] = Field(default_factory=list)
    related: list[RelatedCard] = Field(default_factory=list)
    origin: str = "curated"
    asked_at: list[AskedAt] = Field(default_factory=list)
    verified_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("image", mode="before")
    @classmethod
    def _absent_image_is_none(cls, value: object) -> object:
        """A card with no picture stores `{}`, which is not a `CardImage`.

        The column defaults to an empty dict rather than to NULL so that the
        JSONB shape is uniform in the database; the API prefers `null`, so the
        two representations are reconciled here rather than at every call site.
        """
        return value or None


class Shelf(BaseModel):
    key: str
    title: str
    subtitle: str = ""
    cards: list[CardSummary] = Field(default_factory=list)


class DiscoveryFeed(BaseModel):
    shelves: list[Shelf] = Field(default_factory=list)
    generated_at: datetime
    mode: str = "interesting"
    """Which lens built this feed — 'interesting' or 'useful'."""


class SearchResult(CardSummary):
    matched_by: list[str] = Field(default_factory=list)
    score: float = 0.0


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    semantic: bool = False
    """False when no embedding key is configured, so the UI can say why."""


class DiscoveredQuestionOut(BaseModel):
    """A raw question observed in the wild, before it becomes a card.

    Exposed so the pipeline is visible rather than a black box: these are the
    things people actually asked, and most of them will never earn a card.
    """

    id: uuid.UUID
    raw_text: str
    source_name: str
    source_url: str = ""
    occurrences: int = 1
    engagement: int = 0
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    status: str = "pending"
    """pending | published | rejected"""
    card_slug: str | None = None
    rejected_reason: str = ""


class DiscoveryQueue(BaseModel):
    total: int = 0
    pending: int = 0
    published: int = 0
    rejected: int = 0
    repeated: int = 0
    """Asked in more than one place — the strongest signal a card is warranted."""
    sources: list[dict] = Field(default_factory=list)
    items: list[DiscoveredQuestionOut] = Field(default_factory=list)
    llm_enabled: bool = False
    """When false, nothing can move out of `pending` — triage needs a model."""


class GraphNodeOut(BaseModel):
    id: str
    slug: str
    label: str
    kind: str = "card"
    category: str = ""
    depth: int = 0
    confidence: float = 0.0
    reading_minutes: int = 0


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    relation: str = "related"
    weight: float = 1.0
    reason: str = ""


class GraphOut(BaseModel):
    root: str
    nodes: list[GraphNodeOut] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)
