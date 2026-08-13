"""Question discovery from public Telegram channels.

Telegram publishes a channel's recent posts as plain server-rendered HTML at
`t.me/s/<name>`, with no API key, no login and no browser needed. What it does
not do is tell you which channels are worth reading, and that turns out to be
the entire problem:

    nplusone     20 posts →  0 questions
    kaztag_kz    20 posts →  0 questions
    postnauka    16 posts →  6 questions
    naukaPRO     20 posts → 37 questions

News channels announce things; explainer channels ask things. It is the same
lesson the Threads tag list taught — the population you point at matters more
than any filter you apply afterwards — so the channel list below is curated
and deliberately short rather than broad.

Everything here is Russian and is translated before it enters the pool, for
the same reason as Habr and zakon: the index, the embeddings and both prompts
are English.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.sources.base import (
    DiscoveredQuestion,
    is_cyrillic,
    looks_like_question_headline,
)
from app.services import translation

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(25.0)
PAUSE_SECONDS = 1.5

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Explainer channels only. A channel that reports the news contributes nothing
# — measured above — and costs a request per run to rediscover that.
CHANNELS: tuple[str, ...] = (
    "naukaPRO",
    "postnauka",
    "zanauku",
)

PAGES_PER_CHANNEL = 2
"""`t.me/s/x` shows the ~20 newest posts; `?before=<id>` walks back from there."""

# A link's query string ends in "?v=abc", so a post with a YouTube URL in it
# splits into sentences that "end in a question mark" and are not questions.
# Stripping links first is what stops the harvest filling with fragments like
# "https://www.youtube.com/watch?" — measured on naukaPRO, which puts a link
# in nearly every post.
_URL = re.compile(r"https?://\S+|t\.me/\S+|www\.\S+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_LEADING_DECORATION = re.compile(r"^[\W_]+")

# These channels write in runs: a question, then two more about the same thing
# using a pronoun — "Что такое нейтронные звёзды? … Почему они вращаются
# быстрее?". The follow-ups are perfectly good questions and completely
# meaningless alone, which is exactly what a card title must not be.
_PRONOUN_FRAGMENT = re.compile(
    r"^(?:как|почему|зачем|отчего|когда|где|что|кто|сколько|насколько|куда)\s+"
    r"(?:же\s+)?(?:они|он|она|оно|их|его|её|ее|ею|им|ими|них|нему|неё|нее|"
    r"эт(?:о|и|от|та)|там|тут)\b",
    re.IGNORECASE,
)

# "Но что такое сон?" and "А как эволюция…" continue the sentence before them.
# The question itself is fine once the conjunction goes.
_LEADING_CONJUNCTION = re.compile(r"^(?:но|а|и|так|итак|кстати|причём|причем)\s+", re.IGNORECASE)


def questions_in(text: str) -> list[str]:
    """The question sentences in one post, with links and decoration removed."""
    cleaned = _URL.sub(" ", text or "")
    out: list[str] = []
    for part in _SENTENCE_SPLIT.split(cleaned):
        candidate = _LEADING_DECORATION.sub("", part.strip()).strip()
        candidate = _LEADING_CONJUNCTION.sub("", candidate).strip()
        if not candidate.endswith("?"):
            continue
        if not is_cyrillic(candidate):
            # These channels are Russian; a Latin fragment here is nearly
            # always a stray piece of a URL or a handle.
            continue
        if _PRONOUN_FRAGMENT.match(candidate):
            continue
        if looks_like_question_headline(candidate):
            out.append(candidate)
    return out


def _parse(html: str, channel: str) -> list[DiscoveredQuestion]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[DiscoveredQuestion] = []

    for wrapper in soup.select(".tgme_widget_message"):
        post_id = (wrapper.get("data-post") or "").strip()
        body = wrapper.select_one(".tgme_widget_message_text")
        if body is None:
            continue
        text = " ".join(body.get_text(" ", strip=True).split())

        views = wrapper.select_one(".tgme_widget_message_views")
        engagement = _views_to_int(views.get_text(strip=True) if views else "")

        for index, question in enumerate(questions_in(text)):
            found.append(
                DiscoveredQuestion(
                    raw_text=question,
                    source_name=f"telegram:{channel}",
                    source_url=f"https://t.me/{post_id}" if post_id else "",
                    # A post can carry several questions, so the post id alone
                    # would collide and the pool would keep only one.
                    external_id=f"tg:{post_id or channel}:{index}",
                    engagement=engagement,
                    original_text=question,
                    original_language="ru",
                )
            )
    return found


def _views_to_int(raw: str) -> int:
    """Telegram renders view counts as "12.3K" / "1.1M"."""
    text = raw.strip().upper().replace(",", ".")
    if not text:
        return 0
    multiplier = 1
    if text.endswith("K"):
        multiplier, text = 1_000, text[:-1]
    elif text.endswith("M"):
        multiplier, text = 1_000_000, text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def _oldest_post_number(html: str) -> str:
    """The id to page back from, taken from the earliest post on the page."""
    soup = BeautifulSoup(html, "html.parser")
    numbers = []
    for wrapper in soup.select(".tgme_widget_message"):
        post = (wrapper.get("data-post") or "").rsplit("/", 1)
        if len(post) == 2 and post[1].isdigit():
            numbers.append(int(post[1]))
    return str(min(numbers)) if numbers else ""


async def _channel(client: httpx.AsyncClient, name: str) -> list[DiscoveredQuestion]:
    found: list[DiscoveredQuestion] = []
    before = ""

    for page in range(PAGES_PER_CHANNEL):
        url = f"https://t.me/s/{name}" + (f"?before={before}" if before else "")
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug("telegram %s unavailable: %s", name, exc)
            break

        html = response.text
        # A channel that does not exist still answers 200, with a ~9KB landing
        # page and no posts in it.
        if "tgme_widget_message_text" not in html:
            logger.debug("telegram %s: no posts on page %d", name, page)
            break

        found.extend(_parse(html, name))
        before = _oldest_post_number(html)
        if not before:
            break
        if page + 1 < PAGES_PER_CHANNEL:
            await asyncio.sleep(PAUSE_SECONDS)

    return found


async def collect(
    limit: int = 40, session: AsyncSession | None = None
) -> list[DiscoveredQuestion]:
    """Questions asked by Russian-language explainer channels, translated."""
    found: list[DiscoveredQuestion] = []
    seen: set[str] = set()

    # Per channel rather than overall: naukaPRO alone yields more than a whole
    # run's budget, so a single global limit means the other channels are
    # never reached and the harvest is one channel's editorial line.
    per_channel = max(limit // len(CHANNELS), 8)

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": _BROWSER_UA}
    ) as client:
        for index, channel in enumerate(CHANNELS):
            if index:
                await asyncio.sleep(PAUSE_SECONDS)
            kept = 0
            for item in await _channel(client, channel):
                if item.raw_text in seen:
                    continue
                seen.add(item.raw_text)
                found.append(item)
                kept += 1
                if kept >= per_channel:
                    break

    logger.info("telegram: %d questions passed the filter", len(found))

    if session is not None and found:
        await _translate(session, found)
    return found


async def _translate(session: AsyncSession, items: list[DiscoveredQuestion]) -> None:
    """English into `raw_text`, Russian kept in `original_text`."""
    if not translation.enabled():
        logger.info("telegram: no translator, dropping %d questions", len(items))
        items.clear()
        return

    try:
        english = await translation.to_english_many(
            session, [item.original_text for item in items]
        )
    except Exception as exc:  # noqa: BLE001 — a dead translator must not end the run
        logger.warning("telegram: translation failed, dropping harvest: %s", exc)
        items.clear()
        return

    translated: list[DiscoveredQuestion] = []
    for item, text in zip(items, english):
        cleaned = (text or "").strip()
        if not cleaned or cleaned == item.original_text:
            continue
        item.raw_text = cleaned
        translated.append(item)

    items[:] = translated
