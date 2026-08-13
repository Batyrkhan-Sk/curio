"""Search — present, but deliberately not the front door."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.ai.llm import llm
from app.api.deps import DbSession
from app.schemas.card import SearchResponse, SearchResult
from app.services import search as search_service

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def search(
    session: DbSession,
    q: str = Query(min_length=1, max_length=200),
    category: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> SearchResponse:
    hits = await search_service.hybrid_search(session, q, limit=limit, category=category)

    results = []
    for hit in hits:
        item = SearchResult.model_validate(hit.card)
        item.matched_by = hit.matched_by
        item.score = round(hit.score, 5)
        results.append(item)

    return SearchResponse(
        query=q,
        results=results,
        suggestions=await search_service.suggest(q),
        semantic=llm.embeddings_available,
    )


@router.get("/suggest", response_model=list[str])
async def suggest(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=6, ge=1, le=12),
) -> list[str]:
    return await search_service.suggest(q, limit=limit)
