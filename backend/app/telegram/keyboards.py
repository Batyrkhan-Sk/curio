"""Inline keyboards, and the callback vocabulary behind them.

`callback_data` is capped at 64 *bytes*, which rules out the obvious design of
putting the slug in it — slugs run to 220 characters. Card ids are UUIDs, so
their 32-character hex form leaves room for a verb and an argument and still
fits in half the budget.

    c:<hex>          show the card preview
    l:<hex>:<n>      show explanation level n
    t:<hex>          key terms
    m:<hex>          misconceptions
    x:<hex>          sources
    s:<hex>          toggle save
    r                another random card
    g                open the language picker
    g:<locale>       switch reading language
    w                open the mode picker
    w:<mode>         switch between interesting and useful
    -                inert label, answered and ignored
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote

from app.core.config import settings
from app.services.translation import LANGUAGES
from app.telegram import render
from app.telegram.strings import language_label, t

NOOP = "-"


def card_key(card: Any) -> str:
    return card.id.hex


def parse(data: str) -> tuple[str, str, int | None]:
    """Split callback data into (verb, hex id, integer argument)."""
    parts = (data or "").split(":")
    verb = parts[0] if parts else ""
    ident = parts[1] if len(parts) > 1 else ""
    argument: int | None = None
    if len(parts) > 2:
        try:
            argument = int(parts[2])
        except ValueError:
            argument = None
    return verb, ident, argument


def uuid_from_hex(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(hex=value)
    except (ValueError, AttributeError):
        return None


# --- Links ------------------------------------------------------------------


def card_url(card: Any) -> str | None:
    base = settings.telegram_webapp_url.rstrip("/")
    if not base:
        return None
    return f"{base}/q/{quote(card.slug)}"


def _open_button(card: Any, *, allow_webapp: bool, locale: str) -> dict | None:
    """"Open in Curio", as a Mini App launch where that is possible.

    A `web_app` button is only valid in a private chat and only over HTTPS;
    Telegram rejects the whole keyboard otherwise, which would lose every other
    button on the message. Inline-mode results are excluded too — they can land
    in any chat, so they never get one.
    """
    url = card_url(card)
    if not url:
        return None
    if allow_webapp and settings.telegram_webapp_ready:
        return {"text": t(locale, "btn_open"), "web_app": {"url": url}}
    if url.startswith("https://"):
        return {"text": t(locale, "btn_open"), "url": url}
    # http://localhost is rejected by the Bot API, and a button that 400s the
    # message is worse than no button.
    return None


def _row(*buttons: dict | None) -> list[dict]:
    return [button for button in buttons if button]


# --- Card keyboards ---------------------------------------------------------


def card_keyboard(
    card: Any,
    *,
    level: int | None = None,
    saved: bool = False,
    private: bool = True,
    show_another: bool = False,
    locale: str = "en",
) -> dict:
    """The keyboard under a card message.

    `level` is None on the preview and 1..n while reading, which is the only
    difference between the two states — the preview offers a way in, a level
    offers the way forward and back.
    """
    key = card_key(card)
    total = render.level_count(card)
    rows: list[list[dict]] = []

    if level is None:
        if total:
            first = (card.levels or [{}])[0]
            label = first.get("label", "")
            rows.append(
                [
                    {
                        "text": t(locale, "btn_start_reading", label=label),
                        "callback_data": f"l:{key}:1",
                    }
                ]
            )
    else:
        navigation = _row(
            {"text": "◀", "callback_data": f"l:{key}:{level - 1}"} if level > 1 else None,
            {"text": f"{level}/{total}", "callback_data": NOOP},
            {"text": "▶", "callback_data": f"l:{key}:{level + 1}"} if level < total else None,
        )
        rows.append(navigation)

    extras = _row(
        {"text": "🧠", "callback_data": f"t:{key}"},
        {"text": "⚠️", "callback_data": f"m:{key}"},
        {"text": "📚", "callback_data": f"x:{key}"},
        {
            "text": t(locale, "btn_saved" if saved else "btn_save"),
            "callback_data": f"s:{key}",
        },
    )
    rows.append(extras)

    if level is not None:
        rows.append([{"text": t(locale, "btn_overview"), "callback_data": f"c:{key}"}])

    open_button = _open_button(card, allow_webapp=private, locale=locale)
    another = (
        {"text": t(locale, "btn_another"), "callback_data": "r"} if show_another else None
    )
    if open_button or another:
        rows.append(_row(open_button, another))

    return {"inline_keyboard": [row for row in rows if row]}


def section_keyboard(
    card: Any, *, saved: bool = False, private: bool = True, locale: str = "en"
) -> dict:
    """For the terms / misconceptions / sources views: a way back, and out."""
    key = card_key(card)
    rows = [
        _row(
            {"text": t(locale, "btn_overview"), "callback_data": f"c:{key}"},
            {
                "text": t(locale, "btn_saved" if saved else "btn_save"),
                "callback_data": f"s:{key}",
            },
        )
    ]
    open_button = _open_button(card, allow_webapp=private, locale=locale)
    if open_button:
        rows.append([open_button])
    return {"inline_keyboard": rows}


def results_keyboard(
    cards: list[Any], *, private: bool = True, locale: str = "en"
) -> dict:
    """One button per search hit, numbered to match the message text.

    Numbers rather than titles: a question is a whole sentence, and Telegram
    shrinks the font until a long button label is unreadable.
    """
    rows: list[list[dict]] = []
    row: list[dict] = []
    for number, card in enumerate(cards, start=1):
        row.append({"text": str(number), "callback_data": f"c:{card_key(card)}"})
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    base = settings.telegram_webapp_url.rstrip("/")
    if private and settings.telegram_webapp_ready and base:
        rows.append(
            [{"text": t(locale, "btn_search_app"), "web_app": {"url": base}}]
        )
    return {"inline_keyboard": rows}


def language_keyboard(current: str) -> dict:
    """One button per supported language, the active one marked.

    `g:<locale>` is the verb; it carries no card, so the reader's position is
    untouched by changing language.
    """
    rows = []
    for code in LANGUAGES:
        mark = "✓ " if code == current else ""
        rows.append(
            [{"text": f"{mark}{language_label(code)}", "callback_data": f"g:{code}"}]
        )
    return {"inline_keyboard": rows}


def mode_keyboard(current: str, locale: str = "en") -> dict:
    """Interesting or useful, the active one marked.

    Like the language picker, `w:<mode>` carries no card — changing what the
    bot draws from does not move the reader off whatever they were reading.
    """
    rows = []
    for key in ("interesting", "useful"):
        mark = "✓ " if key == current else ""
        rows.append(
            [{"text": f"{mark}{t(locale, f'mode_{key}')}", "callback_data": f"w:{key}"}]
        )
    return {"inline_keyboard": rows}


def inline_result_keyboard(card: Any, locale: str = "en") -> dict | None:
    """Attached to a card shared into someone else's chat.

    Callback buttons are omitted deliberately: the recipient is not necessarily
    the sender, and answering their taps would mean writing to a profile that
    never asked for one. A link out is the honest affordance.
    """
    url = card_url(card)
    if not url or not url.startswith("https://"):
        return None
    return {"inline_keyboard": [[{"text": t(locale, "btn_read_inline"), "url": url}]]}


def start_keyboard(locale: str = "en", mode: str = "interesting") -> dict:
    rows = [
        [
            {"text": t(locale, "btn_surprise"), "callback_data": "r"},
            {"text": t(locale, "btn_mode"), "callback_data": "w"},
        ],
        [{"text": t(locale, "btn_language"), "callback_data": "g"}],
    ]
    base = settings.telegram_webapp_url.rstrip("/")
    if settings.telegram_webapp_ready and base:
        # The Mini App opens in whichever lens the reader chose in the chat, so
        # the setting means one thing across both halves of the platform.
        url = f"{base}?mode={quote(mode)}" if mode != "interesting" else base
        rows.append([{"text": t(locale, "btn_open_app"), "web_app": {"url": url}}])
    return {"inline_keyboard": rows}
