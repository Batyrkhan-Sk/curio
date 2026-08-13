"""Turning a knowledge card into a Telegram message.

Telegram's HTML mode is not HTML: it accepts a fixed list of inline tags
(`b i u s a code pre blockquote span`), rejects everything else with a 400, and
caps a message at 4096 UTF-16 code units. So this module does three things —
escape, convert the light markdown that synthesised cards carry, and cut to
length on a boundary that reads as deliberate.

The order matters. Truncation happens on the *raw* text, before tags are
introduced, because cutting finished HTML can land inside a tag and Telegram
rejects the whole message. The markdown converter only ever emits balanced
pairs, so a cut that separates `**` from its partner leaves literal asterisks
rather than an unclosed `<b>`.
"""

from __future__ import annotations

import html
import re
from typing import Any

from app.telegram.strings import difficulty_label, t

# Every function here takes something *card-shaped* rather than a `Card`: in a
# non-English reading language it is handed a `localize.LocalCard` whose
# strings have already been translated. Formatting is the same either way.
CardLike = Any

MAX_MESSAGE = 4096
"""Telegram's hard limit. Bodies are cut well below it to leave room for the
title, the level header, and the footer that share the message."""

LEVEL_EMOJI = ("🌱", "🔗", "🔬", "⚙️", "🎓")
"""One per level, 1..5: intuition, analogy, real example, technical, expert."""


def escape(text: str) -> str:
    return html.escape(str(text or ""), quote=False)


_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_CODE = re.compile(r"`([^`\n]+?)`")
_HEADING = re.compile(r"^#{1,6}\s*(.+)$", re.MULTILINE)
_BULLET = re.compile(r"^[-*]\s+", re.MULTILINE)


def rich(text: str) -> str:
    """Escape, then re-introduce the few tags Telegram understands.

    Curated cards are plain prose, but synthesised ones come back from the
    model with markdown in them, and showing a reader literal `**` is worse
    than the two lines it costs to convert it.
    """
    out = escape(text)
    out = _HEADING.sub(r"<b>\1</b>", out)
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _ITALIC.sub(r"<i>\1</i>", out)
    out = _CODE.sub(r"<code>\1</code>", out)
    out = _BULLET.sub("• ", out)
    return out.strip()


def clip(text: str, limit: int) -> tuple[str, bool]:
    """Cut raw text to `limit`, preferring a paragraph then a sentence break.

    Returns the text and whether anything was removed, so the caller can say so
    rather than trailing off mid-thought.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text, False

    window = text[:limit]
    for boundary in ("\n\n", ". ", "! ", "? "):
        cut = window.rfind(boundary)
        # Refuse a boundary that throws away most of the allowance — better a
        # hard cut near the limit than a third of the text.
        if cut > limit * 0.6:
            return window[: cut + len(boundary)].strip(), True
    return window.rstrip() + "…", True


def _levels(card: CardLike) -> list[dict[str, Any]]:
    levels = [lvl for lvl in (card.levels or []) if str(lvl.get("body", "")).strip()]
    return sorted(levels, key=lambda lvl: int(lvl.get("level", 0)))


def level_count(card: CardLike) -> int:
    return len(_levels(card))


def _meta_line(card: CardLike, locale: str) -> str:
    bits = []
    if card.category is not None:
        bits.append(escape(card.category.name))
    bits.append(t(locale, "minutes", n=card.reading_minutes))
    if card.difficulty and card.difficulty != "beginner":
        bits.append(escape(difficulty_label(locale, card.difficulty)))
    bits.append(t(locale, "confidence", n=round((card.confidence or 0) * 100)))
    return "<i>" + " · ".join(bits) + "</i>"


def card_intro(card: CardLike, locale: str = "en") -> str:
    """The card as a preview: the question, the one-sentence answer, the meta."""
    answer, _ = clip(card.one_sentence_answer, 900)
    parts = [
        f"🔭 <b>{escape(card.title)}</b>",
        "",
        rich(answer),
    ]

    if card.summary and card.summary.strip() != card.one_sentence_answer.strip():
        summary, _ = clip(card.summary, 700)
        parts += ["", rich(summary)]

    parts += ["", _meta_line(card, locale)]
    return "\n".join(parts)


def level_view(card: CardLike, index: int, locale: str = "en") -> str:
    """One explanation level. `index` is 1-based and assumed already clamped."""
    levels = _levels(card)
    if not levels:
        return card_intro(card, locale)

    index = max(1, min(index, len(levels)))
    level = levels[index - 1]
    emoji = LEVEL_EMOJI[min(index, len(LEVEL_EMOJI)) - 1]
    label = escape(level.get("label", f"Level {index}"))

    body, truncated = clip(str(level.get("body", "")), 3400)
    position = t(locale, "level_position", index=index, total=len(levels))
    parts = [
        f"🔭 <b>{escape(card.title)}</b>",
        f"{emoji} <b>{label}</b>  <i>· {position}</i>",
        "",
        rich(body),
    ]
    if truncated:
        parts += ["", f"<i>{t(locale, 'trimmed')}</i>"]
    return "\n".join(parts)


def terms_view(card: CardLike, locale: str = "en") -> str:
    terms = [term for term in (card.key_terms or []) if term.get("term")]
    if not terms:
        return (
            f"🔭 <b>{escape(card.title)}</b>\n\n<i>{t(locale, 'no_terms')}</i>"
        )

    parts = [
        f"🔭 <b>{escape(card.title)}</b>",
        f"🧠 <b>{t(locale, 'key_terms')}</b>",
        "",
    ]
    for term in terms[:12]:
        # `plain_definition` is the schema's name (see schemas/card.py); the
        # alternatives are what a model occasionally returns instead.
        raw = (
            term.get("plain_definition")
            or term.get("definition")
            or term.get("meaning")
            or ""
        )
        definition, _ = clip(str(raw), 260)
        if definition:
            parts.append(f"<b>{escape(term['term'])}</b> — {rich(definition)}")
        else:
            parts.append(f"<b>{escape(term['term'])}</b>")
        parts.append("")
    return "\n".join(parts).strip()


def myths_view(card: CardLike, locale: str = "en") -> str:
    myths = [m for m in (card.misconceptions or []) if m.get("myth") or m.get("claim")]
    if not myths:
        return (
            f"🔭 <b>{escape(card.title)}</b>\n\n"
            f"<i>{t(locale, 'no_myths')}</i>"
        )

    parts = [
        f"🔭 <b>{escape(card.title)}</b>",
        f"⚠️ <b>{t(locale, 'myths')}</b>",
        "",
    ]
    for myth in myths[:6]:
        claim = str(myth.get("myth") or myth.get("claim") or "")
        reality = str(myth.get("reality") or myth.get("correction") or myth.get("truth") or "")
        claim_text, _ = clip(claim, 280)
        reality_text, _ = clip(reality, 420)
        parts.append(f"❌ <s>{rich(claim_text)}</s>")
        if reality_text:
            parts.append(f"✅ {rich(reality_text)}")
        parts.append("")
    return "\n".join(parts).strip()


def sources_view(card: CardLike, locale: str = "en") -> str:
    sources = list(card.sources or [])
    header = [
        f"🔭 <b>{escape(card.title)}</b>",
        f"📚 <b>{t(locale, 'sources')}</b>",
        "",
    ]
    if not sources:
        return "\n".join(header + [f"<i>{t(locale, 'no_sources')}</i>"])

    parts = list(header)
    for source in sorted(sources, key=lambda s: s.reliability or 0, reverse=True)[:8]:
        title = escape(source.title or source.url)
        marker = {"contradicts": "⚡", "context": "•"}.get(source.supports, "·")
        publisher = f" — {escape(source.publisher)}" if source.publisher else ""
        if source.url:
            parts.append(f'{marker} <a href="{html.escape(source.url, quote=True)}">{title}</a>{publisher}')
        else:
            parts.append(f"{marker} {title}{publisher}")

    if card.confidence_reason:
        reason, _ = clip(card.confidence_reason, 500)
        parts += ["", f"<i>{rich(reason)}</i>"]
    return "\n".join(parts)


def results_list(
    cards: list[CardLike], *, query: str, locale: str = "en", note: str = ""
) -> str:
    """The text half of a search reply. The buttons carry the actual links."""
    if not cards:
        return (
            t(locale, "nothing_found", query=escape(query))
            + "\n\n"
            + f"<i>{t(locale, 'search_hint')}</i>"
        )

    parts = [f"🔎 <b>{escape(query)}</b>"]
    # When the query was translated before searching, say so — otherwise the
    # results look unrelated to what was typed.
    if note:
        parts.append(f"<i>{escape(note)}</i>")
    parts.append("")
    for number, card in enumerate(cards, start=1):
        answer, _ = clip(card.one_sentence_answer, 150)
        parts.append(f"<b>{number}. {escape(card.title)}</b>")
        parts.append(f"<i>{rich(answer)}</i>")
        parts.append("")
    return "\n".join(parts).strip()


def welcome(name: str, *, locale: str = "en", bot_username: str = "") -> str:
    greeting = (
        t(locale, "welcome_greeting", name=escape(name))
        if name
        else t(locale, "welcome_greeting_anon")
    )
    return t(
        locale,
        "welcome",
        greeting=greeting,
        bot=escape(bot_username) or "curio_bot",
    )


def help_text(bot_username: str = "", locale: str = "en") -> str:
    mention = f"@{escape(bot_username)}" if bot_username else "@yourbot"
    return t(locale, "help", mention=mention)


def truncate_message(text: str) -> str:
    """Final guard before sending. Nothing should reach this; a card with an
    unusually long title and a full level could."""
    if len(text) <= MAX_MESSAGE:
        return text
    return text[: MAX_MESSAGE - 1].rstrip() + "…"
