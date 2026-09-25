"""Serving a card's picture from Curio's own origin.

Nothing links straight to `upload.wikimedia.org` or `i.redd.it`, for three
reasons that each independently require a proxy:

  * The service worker ignores cross-origin requests (`public/sw.js`), so a
    hotlinked image is the one part of a saved card that fails on a train.
  * Wikimedia asks for a User-Agent identifying the project, and Reddit's
    preview host serves datacentre addresses a block page unless the request
    looks like a browser. Neither is something a reader's browser will send.
  * Reddit's signed preview URLs are long, ugly and expire; the card should
    hold a stable address that outlives them.

The route is keyed by card id rather than taking a URL. A proxy that fetches
whatever URL it is handed is a server-side request forgery hole regardless of
how carefully the query parameter is validated, so the only addresses reachable
here are ones already written to a card row by ingestion — and those went
through the host allowlist in `ingestion/images.py` on the way in, which is
checked again below because a database row is not a promise.
"""

from __future__ import annotations

import logging
import uuid
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings
from app.ingestion.images import allowed_host
from app.models import Card

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media", tags=["media"])

TIMEOUT = httpx.Timeout(20.0, connect=10.0)

MAX_BYTES = 8 * 1024 * 1024
"""A lead image that exceeds this is a scan of a document, not an illustration."""

CHUNK = 64 * 1024

CACHE_CONTROL = "public, max-age=604800, stale-while-revalidate=86400"
"""A week. The bytes behind a card's image never change — a different picture
means a different URL — so the only thing this costs is a re-fetch after a
card is re-synthesised."""

_WIKIMEDIA_UA = "curio/0.1 (https://github.com/; knowledge cards; contact via repo)"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _headers_for(provider: str) -> dict[str, str]:
    if provider == "reddit":
        # Reddit serves its preview host to browsers and blocks polite,
        # project-identifying agents — the same inversion `sources/forums.py`
        # already works around for the Atom feeds.
        return {"User-Agent": _BROWSER_UA, "Accept": "image/*"}
    return {"User-Agent": _WIKIMEDIA_UA, "Accept": "image/*"}


@router.get("/{card_id}")
async def card_image(card_id: uuid.UUID, session: DbSession) -> Response:
    """Stream the picture attached to one card."""
    image = await session.scalar(select(Card.image).where(Card.id == card_id))
    url = (image or {}).get("url") or ""

    if not url:
        raise HTTPException(status_code=404, detail="This card has no image.")
    if not allowed_host(url):
        # Reachable only if a row predates the allowlist or was written by hand.
        logger.warning("card %s holds an image on a disallowed host", card_id)
        raise HTTPException(status_code=404, detail="This card has no image.")

    client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True)
    try:
        request = client.build_request(
            "GET", url, headers=_headers_for(str((image or {}).get("provider") or ""))
        )
        upstream = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.info("image fetch failed for card %s: %s", card_id, exc)
        raise HTTPException(status_code=502, detail="Image source unreachable.") from exc

    content_type = upstream.headers.get("content-type", "")
    if upstream.status_code != 200 or not content_type.startswith("image/"):
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail="Image source returned no image.")

    async def stream() -> AsyncIterator[bytes]:
        sent = 0
        try:
            async for chunk in upstream.aiter_bytes(CHUNK):
                sent += len(chunk)
                if sent > MAX_BYTES:
                    # Truncating mid-image is ugly, but the alternative is
                    # buffering an unbounded upstream response into memory on
                    # the say-so of a third party.
                    logger.warning("image for card %s exceeded %d bytes", card_id, MAX_BYTES)
                    break
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        media_type=content_type.split(";")[0],
        headers={"Cache-Control": CACHE_CONTROL},
    )


def public_url(card_id: uuid.UUID) -> str:
    """The absolute address of a card's image.

    Needed because Telegram fetches the picture from its own servers rather
    than from the reader's client, so a relative path is meaningless to it.
    Returns "" when no public origin is configured, which the bot reads as
    "send this card without a picture" — the same as having no image at all.
    """
    base = (settings.telegram_public_url or settings.telegram_webapp_url or "").rstrip("/")
    # Telegram will not fetch a preview over plain http, and a localhost address
    # is unreachable from its servers in the first place, so an http origin is
    # treated as no origin rather than as a link that quietly never renders.
    if not base.startswith("https://"):
        return ""
    return f"{base}/api/v1/media/{card_id}"
