"""The Telegram Bot API client.

Raw httpx rather than a bot framework. The framework's value is its dispatcher
and its polling loop, and this bot has neither — FastAPI already owns the
routing and Telegram delivers updates to a webhook. What is left is a dozen
`POST /bot<token>/<method>` calls, which is less code than the adapter would be.

Every method returns the unwrapped `result` field, or raises `TelegramError`.
Send failures are logged and swallowed at the call sites that are reacting to a
user action: a webhook that raises makes Telegram retry the same update, which
turns one failed reply into a loop of them.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

API_ROOT = "https://api.telegram.org"

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class TelegramError(RuntimeError):
    """A non-ok response from the Bot API."""

    def __init__(self, method: str, code: int, description: str) -> None:
        super().__init__(f"{method} failed [{code}]: {description}")
        self.method = method
        self.code = code
        self.description = description


class TelegramNotConfigured(RuntimeError):
    pass


async def call(method: str, **payload: Any) -> Any:
    """Invoke one Bot API method.

    `None` values are stripped rather than sent: the API rejects an explicit
    null for most optional parameters, and building the payloads conditionally
    at every call site is noise.
    """
    if not settings.telegram_bot_token:
        raise TelegramNotConfigured(
            "TELEGRAM_BOT_TOKEN is not set — get one from @BotFather"
        )

    body = {k: v for k, v in payload.items() if v is not None}
    url = f"{API_ROOT}/bot{settings.telegram_bot_token}/{method}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for attempt in range(3):
            try:
                response = await client.post(url, json=body)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise TelegramError(method, 0, str(exc)) from exc
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            data = response.json()
            if data.get("ok"):
                return data.get("result")

            code = int(data.get("error_code", response.status_code))
            description = str(data.get("description", ""))

            # 429 carries the exact wait in retry_after. Anything else is
            # either our bug (400) or Telegram's (5xx); only the latter is
            # worth a second attempt.
            if code == 429:
                wait = float(data.get("parameters", {}).get("retry_after", 1))
                await asyncio.sleep(min(wait, 10))
                continue
            if code >= 500 and attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            raise TelegramError(method, code, description)

    raise TelegramError(method, 0, "retries exhausted")


async def try_call(method: str, **payload: Any) -> Any | None:
    """`call` for fire-and-forget replies: never raises, only logs.

    Used everywhere the caller is a webhook handler. Letting the exception
    escape would fail the webhook, and Telegram redelivers a failed update —
    so one 400 becomes the same broken message sent over and over.
    """
    try:
        return await call(method, **payload)
    except (TelegramError, TelegramNotConfigured) as exc:
        logger.warning("telegram %s: %s", method, exc)
        return None


# --- Messages ---------------------------------------------------------------


def _preview(url: str, *, above: bool) -> dict:
    """Build `LinkPreviewOptions` for a card that has a picture.

    This is how an image gets onto a card message, and the reason it is not
    `sendPhoto` is worth stating once. A message sent with `sendPhoto` is a
    *photo* message: its caption is capped at 1024 characters against 4096 for
    text, and `editMessageText` refuses to touch it. Curio's whole reading
    model is editing one message in place as the reader moves between levels
    (see `telegram/handlers.py`), so a photo message would either truncate
    every level to a quarter of its length or break every arrow button.

    A forced link preview keeps the message a text message. Nothing about the
    navigation changes, the full text budget survives, and Telegram fetches the
    image itself — which is also why the URL has to be publicly resolvable.
    """
    if not url:
        return {"is_disabled": True}
    return {
        "is_disabled": False,
        "url": url,
        "prefer_large_media": True,
        "show_above_text": above,
    }


async def send_message(
    chat_id: int | str,
    text: str,
    *,
    reply_markup: dict | None = None,
    disable_preview: bool = True,
    reply_to: int | None = None,
    preview_url: str = "",
    preview_above: bool = False,
) -> Any | None:
    return await try_call(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        link_preview_options=(
            _preview(preview_url, above=preview_above)
            if preview_url
            else {"is_disabled": disable_preview}
        ),
        reply_markup=reply_markup,
        reply_parameters={"message_id": reply_to} if reply_to else None,
    )


async def edit_message(
    chat_id: int | str,
    message_id: int,
    text: str,
    *,
    reply_markup: dict | None = None,
    preview_url: str = "",
    preview_above: bool = False,
) -> Any | None:
    return await try_call(
        "editMessageText",
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        parse_mode="HTML",
        link_preview_options=_preview(preview_url, above=preview_above),
        reply_markup=reply_markup,
    )


async def edit_markup(
    chat_id: int | str, message_id: int, reply_markup: dict | None
) -> Any | None:
    return await try_call(
        "editMessageReplyMarkup",
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=reply_markup,
    )


async def answer_callback(
    callback_id: str, text: str = "", *, alert: bool = False
) -> Any | None:
    """Always call this, even with no text.

    Telegram shows a spinner on the tapped button until the callback is
    answered, and leaves it spinning for a minute if it never is.
    """
    return await try_call(
        "answerCallbackQuery",
        callback_query_id=callback_id,
        text=text or None,
        show_alert=alert or None,
    )


async def answer_inline(
    inline_query_id: str,
    results: list[dict],
    *,
    cache_time: int = 60,
    next_offset: str = "",
    button: dict | None = None,
) -> Any | None:
    return await try_call(
        "answerInlineQuery",
        inline_query_id=inline_query_id,
        results=results,
        cache_time=cache_time,
        next_offset=next_offset or None,
        button=button,
    )


async def send_chat_action(chat_id: int | str, action: str = "typing") -> Any | None:
    return await try_call("sendChatAction", chat_id=chat_id, action=action)


# --- One-time setup ---------------------------------------------------------


async def get_me() -> dict:
    return await call("getMe")


async def set_webhook(url: str, secret: str) -> Any:
    return await call(
        "setWebhook",
        url=url,
        secret_token=secret,
        # Everything else (edited messages, channel posts, reactions) would be
        # delivered and dropped, so it is not requested in the first place.
        allowed_updates=["message", "callback_query", "inline_query"],
        # Updates queued while the bot was down are almost always stale by the
        # time it returns, and replying to them looks like a ghost.
        drop_pending_updates=True,
    )


async def delete_webhook() -> Any:
    return await call("deleteWebhook", drop_pending_updates=True)


async def get_webhook_info() -> dict:
    return await call("getWebhookInfo")


async def set_my_commands(
    commands: list[dict[str, str]], language_code: str | None = None
) -> Any:
    """Set the command list, optionally for one client language.

    Telegram scopes commands by the *client's* language setting, which is not
    the same thing as the reading language the bot stores per reader — this
    only decides which hints appear in the command menu.
    """
    return await call("setMyCommands", commands=commands, language_code=language_code)


async def set_chat_menu_button(webapp_url: str | None) -> Any:
    """The button beside the message box. Opens the Mini App when set."""
    if webapp_url:
        button = {
            "type": "web_app",
            "text": "Read Curio",
            "web_app": {"url": webapp_url},
        }
    else:
        button = {"type": "commands"}
    return await call("setChatMenuButton", menu_button=button)


async def set_my_description(description: str, short: str) -> Any:
    await call("setMyDescription", description=description)
    return await call("setMyShortDescription", short_description=short)
