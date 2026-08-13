"""Building and walking the knowledge graph."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Card, CardConcept, CardLink, Concept, ConceptEdge
from app.services.embeddings import similar_cards

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GraphNode:
    id: str
    slug: str
    label: str
    kind: str  # "card" | "concept"
    category: str = ""
    depth: int = 0
    confidence: float = 0.0
    reading_minutes: int = 0


@dataclass(slots=True)
class GraphView:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)


async def upsert_concept(
    session: AsyncSession,
    name: str,
    *,
    plain_definition: str = "",
    category_slug: str = "",
) -> Concept:
    slug = slugify(name)[:160]
    existing = await session.scalar(select(Concept).where(Concept.slug == slug))
    if existing:
        # Keep the first good definition; later cards may phrase it worse.
        if not existing.plain_definition and plain_definition:
            existing.plain_definition = plain_definition
        return existing

    concept = Concept(
        slug=slug,
        name=name.strip(),
        plain_definition=plain_definition,
        category_slug=category_slug,
    )
    session.add(concept)
    await session.flush()
    return concept


async def link_card_concept(
    session: AsyncSession,
    card_id: uuid.UUID,
    concept_id: uuid.UUID,
    *,
    role: str = "covers",
    weight: float = 1.0,
) -> None:
    stmt = (
        pg_insert(CardConcept)
        .values(
            id=uuid.uuid4(),
            card_id=card_id,
            concept_id=concept_id,
            role=role,
            weight=weight,
        )
        .on_conflict_do_nothing(constraint="uq_card_concept")
    )
    await session.execute(stmt)


async def link_concepts(
    session: AsyncSession,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    *,
    relation: str = "related",
    weight: float = 1.0,
) -> None:
    if source_id == target_id:
        return
    stmt = (
        pg_insert(ConceptEdge)
        .values(
            id=uuid.uuid4(),
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            weight=weight,
        )
        .on_conflict_do_nothing(constraint="uq_concept_edge")
    )
    await session.execute(stmt)


async def link_cards(
    session: AsyncSession,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    *,
    relation: str = "related",
    weight: float = 1.0,
    reason: str = "",
    bidirectional: bool = True,
) -> None:
    if source_id == target_id:
        return

    pairs = [(source_id, target_id)]
    if bidirectional and relation == "related":
        pairs.append((target_id, source_id))

    for src, dst in pairs:
        stmt = (
            pg_insert(CardLink)
            .values(
                id=uuid.uuid4(),
                source_id=src,
                target_id=dst,
                relation=relation,
                weight=weight,
                reason=reason,
            )
            .on_conflict_do_nothing(constraint="uq_card_link")
        )
        await session.execute(stmt)


async def connect_by_shared_concepts(session: AsyncSession, card: Card) -> int:
    """Link a card to others that teach the same concepts.

    This is what makes the graph hold together without an LLM: two cards that
    both cover "thermal expansion" are related whether or not a model said so.
    """
    concept_ids = list(
        (
            await session.execute(
                select(CardConcept.concept_id).where(CardConcept.card_id == card.id)
            )
        ).scalars()
    )
    if not concept_ids:
        return 0

    rows = await session.execute(
        select(CardConcept.card_id, Concept.name)
        .join(Concept, Concept.id == CardConcept.concept_id)
        .where(CardConcept.concept_id.in_(concept_ids), CardConcept.card_id != card.id)
    )

    shared: dict[uuid.UUID, list[str]] = {}
    for other_id, concept_name in rows:
        shared.setdefault(other_id, []).append(concept_name)

    created = 0
    for other_id, names in shared.items():
        # One shared concept is a weak signal; two or more is a real link.
        weight = min(1.0, 0.4 + 0.3 * len(names))
        if len(names) < 2 and weight < 0.7:
            continue
        await link_cards(
            session,
            card.id,
            other_id,
            relation="related",
            weight=weight,
            reason=f"Both explain {names[0]}" if len(names) == 1 else
                   f"Share {len(names)} concepts including {names[0]}",
        )
        created += 1
    return created


async def connect_by_similarity(
    session: AsyncSession, card: Card, *, limit: int = 6
) -> int:
    """Fill remaining connections using vector neighbours."""
    if card.embedding is None:
        return 0
    neighbours = await similar_cards(
        session, list(card.embedding), limit=limit, exclude_id=card.id, max_distance=0.55
    )
    for other, distance in neighbours:
        await link_cards(
            session,
            card.id,
            other.id,
            relation="related",
            weight=round(1.0 - distance, 3),
            reason="Closely related idea",
        )
    return len(neighbours)


async def related_cards(
    session: AsyncSession, card_id: uuid.UUID, *, limit: int = 8
) -> list[tuple[Card, CardLink]]:
    rows = await session.execute(
        select(Card, CardLink)
        .options(selectinload(Card.category))
        .join(CardLink, CardLink.target_id == Card.id)
        .where(CardLink.source_id == card_id, Card.status == "published")
        .order_by(CardLink.weight.desc())
        .limit(limit)
    )
    return [(card, link) for card, link in rows]


async def neighbourhood(
    session: AsyncSession,
    card_id: uuid.UUID,
    *,
    depth: int = 2,
    max_nodes: int = 40,
) -> GraphView:
    """Breadth-first walk outwards from one card, for the graph view.

    Capped at `max_nodes` because past roughly forty nodes a force layout stops
    being a map and becomes a hairball.
    """
    view = GraphView()
    seen: set[uuid.UUID] = set()
    frontier = [card_id]

    for level in range(depth + 1):
        if not frontier or len(seen) >= max_nodes:
            break

        rows = await session.execute(
            select(Card).options(selectinload(Card.category)).where(Card.id.in_(frontier))
        )
        cards = list(rows.scalars().unique())
        for card in cards:
            if card.id in seen:
                continue
            seen.add(card.id)
            view.nodes.append(
                GraphNode(
                    id=str(card.id),
                    slug=card.slug,
                    label=card.title,
                    kind="card",
                    category=card.category.slug if card.category else "",
                    depth=level,
                    confidence=card.confidence,
                    reading_minutes=card.reading_minutes,
                )
            )

        if level == depth:
            break

        link_rows = await session.execute(
            select(CardLink)
            .where(CardLink.source_id.in_([c.id for c in cards]))
            .order_by(CardLink.weight.desc())
        )
        next_frontier: list[uuid.UUID] = []
        for link in link_rows.scalars():
            view.edges.append(
                {
                    "source": str(link.source_id),
                    "target": str(link.target_id),
                    "relation": link.relation,
                    "weight": link.weight,
                    "reason": link.reason,
                }
            )
            if link.target_id not in seen and len(seen) + len(next_frontier) < max_nodes:
                next_frontier.append(link.target_id)
        frontier = next_frontier

    # Drop edges pointing at nodes we never expanded, so the client never has
    # to render a dangling arrow.
    node_ids = {n.id for n in view.nodes}
    view.edges = [
        e for e in view.edges if e["source"] in node_ids and e["target"] in node_ids
    ]
    # Deduplicate the two directions of a symmetric "related" pair.
    unique: dict[tuple[str, str], dict] = {}
    for edge in view.edges:
        key = tuple(sorted((edge["source"], edge["target"])))
        if key not in unique or edge["weight"] > unique[key]["weight"]:
            unique[key] = edge
    view.edges = list(unique.values())
    return view
