"""Verifying the `initData` a Telegram Mini App hands its backend.

The webview receives a signed blob describing who opened it. It arrives through
the browser, so it is attacker-controlled until the signature is checked — and
the check is the only thing standing between "this is Telegram user 12345" and
anyone typing that number into a request.

Telegram's scheme, from the Mini Apps documentation:

    secret_key = HMAC_SHA256(key="WebAppData", message=<bot token>)
    expected   = HMAC_SHA256(key=secret_key, message=<data check string>)

where the data check string is every field except `hash`, as `key=value`,
sorted by key, joined with newlines.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_AGE_SECONDS = 24 * 60 * 60
"""How old a signed payload may be. Telegram keeps the same initData for the
lifetime of the webview, so this is generous on purpose; its job is to stop a
captured blob being replayed indefinitely, not to expire a live session."""


class InitDataError(ValueError):
    """The payload was missing, malformed, unsigned, forged, or stale."""


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""
    is_premium: bool = False

    @property
    def display_name(self) -> str:
        full = " ".join(part for part in (self.first_name, self.last_name) if part)
        return full or self.username or "Curious reader"


def parse_user(raw: dict) -> TelegramUser:
    return TelegramUser(
        id=int(raw["id"]),
        first_name=str(raw.get("first_name", ""))[:128],
        last_name=str(raw.get("last_name", ""))[:128],
        username=str(raw.get("username", ""))[:64],
        language_code=str(raw.get("language_code", ""))[:16],
        is_premium=bool(raw.get("is_premium", False)),
    )


def verify(init_data: str) -> TelegramUser:
    """Validate a raw `initData` query string and return the user in it."""
    if not settings.telegram_bot_token:
        raise InitDataError("Telegram is not configured on this server")
    if not init_data:
        raise InitDataError("initData missing")

    try:
        fields = dict(parse_qsl(init_data, strict_parsing=True, keep_blank_values=True))
    except ValueError as exc:
        raise InitDataError("initData is not a valid query string") from exc

    received_hash = fields.pop("hash", "")
    if not received_hash:
        raise InitDataError("initData carries no hash")

    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    # Constant time: a plain `==` on a hex digest leaks its prefix through
    # timing, and the whole point of this function is that the digest is secret.
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("initData signature does not match")

    auth_date = fields.get("auth_date", "")
    if auth_date.isdigit():
        age = time.time() - int(auth_date)
        if age > MAX_AGE_SECONDS:
            raise InitDataError("initData has expired — reopen the app")
    else:
        raise InitDataError("initData carries no auth_date")

    raw_user = fields.get("user", "")
    if not raw_user:
        # Happens when the app is opened from an inline keyboard in a channel,
        # where Telegram deliberately withholds the identity.
        raise InitDataError("initData carries no user")

    try:
        return parse_user(json.loads(raw_user))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise InitDataError("initData user field is malformed") from exc
