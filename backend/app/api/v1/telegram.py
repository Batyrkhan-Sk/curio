"""Telegram endpoints: the update webhook, and Mini App sign-in.

The webhook is unauthenticated in the ordinary sense — Telegram will not send a
bearer token — so it is protected by the secret set alongside the URL in
`setWebhook`, which Telegram echoes in a header on every delivery.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.core.config import settings
from app.services import telegram as telegram_api
from app.telegram import handlers
from app.telegram.initdata import InitDataError, verify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])

PROFILE_HEADER = "X-Curio-Profile"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


@router.post("/webhook", include_in_schema=False)
async def webhook(
    request: Request,
    session: DbSession,
    secret_token: Annotated[str | None, Header(alias=SECRET_HEADER)] = None,
) -> Response:
    """Receive one update.

    Two rules govern the response. It must be 200 for anything Telegram should
    not resend — including updates this bot cannot handle — because a non-2xx
    is redelivered with backoff, and a handler bug would otherwise become an
    infinite retry of the same broken reply. And it must be fast: Telegram
    times out at 60 seconds and starts redelivering.

    `handle_update` therefore swallows its own exceptions, and this route is
    only responsible for authenticating the caller.
    """
    if not settings.telegram_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram is not configured",
        )

    # A missing configured secret is a misconfiguration, not an open door: the
    # webhook URL is public, so without the check anyone could post updates
    # claiming to be any user.
    if not settings.telegram_webhook_secret:
        logger.error("TELEGRAM_WEBHOOK_SECRET is not set — refusing updates")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram webhook secret is not configured",
        )

    if secret_token != settings.telegram_webhook_secret:
        logger.warning("rejected a telegram webhook call with a bad secret")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bad secret token"
        )

    try:
        update: dict[str, Any] = await request.json()
    except ValueError:
        return Response(status_code=status.HTTP_200_OK)

    await handlers.handle_update(session, update)
    return Response(status_code=status.HTTP_200_OK)


class MiniAppAuth(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)
    """`window.Telegram.WebApp.initData`, verbatim."""

    profile_key: str | None = Field(default=None, max_length=64)
    """The anonymous profile the browser was already using, if any. Adopted on
    first sign-in so a reader who used the web app first keeps their history."""


class MiniAppSession(BaseModel):
    profile_key: str
    display_name: str
    telegram_id: int
    username: str = ""
    streak_days: int = 0
    preferred_level: int = 1


@router.post("/auth", response_model=MiniAppSession)
async def authenticate(
    payload: MiniAppAuth,
    session: DbSession,
    response: Response,
) -> MiniAppSession:
    """Exchange signed Mini App `initData` for the reader's profile key.

    The key is returned in the body *and* in `X-Curio-Profile`, so the webview
    can store it and every later request looks exactly like the ordinary web
    app's — the Mini App is the same frontend, not a second client.
    """
    if not settings.telegram_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram is not configured",
        )

    try:
        user = verify(payload.init_data)
    except InitDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    link = await handlers.link_for(
        session, user, adopt_profile_key=payload.profile_key
    )
    profile = link.profile
    await session.commit()

    response.headers[PROFILE_HEADER] = profile.key
    return MiniAppSession(
        profile_key=profile.key,
        display_name=profile.display_name,
        telegram_id=user.id,
        username=user.username,
        streak_days=profile.streak_days,
        preferred_level=profile.preferred_level,
    )


@router.get("/status")
async def status_report() -> dict:
    """Whether the bot is wired up, and what Telegram thinks of the webhook.

    Deliberately reports no token material — just enough to tell "the token is
    wrong" apart from "the webhook URL is wrong", which is most of debugging
    this integration.
    """
    report: dict[str, Any] = {
        "configured": settings.telegram_enabled,
        "webapp_url": settings.telegram_webapp_url or None,
        "webapp_https": settings.telegram_webapp_ready,
        "webhook_secret_set": bool(settings.telegram_webhook_secret),
    }
    if not settings.telegram_enabled:
        return report

    try:
        me = await telegram_api.get_me()
        report["bot"] = {"username": me.get("username"), "id": me.get("id")}
    except Exception as exc:
        report["bot_error"] = str(exc)
        return report

    try:
        info = await telegram_api.get_webhook_info()
        report["webhook"] = {
            "url": info.get("url"),
            "pending_update_count": info.get("pending_update_count"),
            "last_error_message": info.get("last_error_message"),
            "last_error_date": info.get("last_error_date"),
        }
    except Exception as exc:
        report["webhook_error"] = str(exc)

    return report
