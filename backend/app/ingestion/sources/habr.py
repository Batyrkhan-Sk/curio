"""Question discovery from Habr — the Russian-language IT community.

Two surfaces, for two different kinds of curiosity:

* **Хабр Q&A** (`qna.habr.com`) — people asking IT questions outright. This is
  the richer source, and also the noisier one: a Q&A site for working
  developers is mostly support requests, so the pre-filter does real work here
  rather than the token amount it does on Stack Exchange.
* **Habr articles** (`habr.com`) — only those whose *title* is a question.
  Somebody wrote a whole article to answer it, which is a strong signal that
  the question is one people keep asking.

Habr publishes no documented API. Q&A has an RSS feed that is linked from its
own pages but appears nowhere in any documentation, and the listing pages are
plain server-rendered HTML. So: scrape the listing that is ordered the way we
want, fall back to the feed that is ordered the way it is. Both are treated as
things that can vanish without notice, which is why neither is allowed to
raise.

Everything here comes back in Russian and is translated to English before it
enters the pool — the index, the embeddings and both AI prompts are English,
and a Russian question in an English pool matches nothing and duplicates
everything. The original wording is kept alongside so the card can cite what
was actually asked.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.sources.base import (
    DiscoveredQuestion,
    looks_like_durable_question,
    looks_like_question_headline,
    question_from_headline,
)
from app.services import translation

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(25.0)

# Habr serves its own pages to browsers and answers a bare client with a
# challenge page.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

QNA_LISTINGS = (
    # "Интересные вопросы" — Habr's own ranking of what is worth answering,
    # which is a far better prior than recency.
    "https://qna.habr.com/questions/interesting",
    "https://qna.habr.com/questions",
)

QNA_RSS = "https://qna.habr.com/rss/questions_latest"

ARTICLE_FEEDS = (
    # The "best" feeds carry a readership signal; the hubs carry subject
    # matter. Measured yields differ by an order of magnitude between hubs:
    # popular science, physics and astronomy ask durable questions in their
    # titles, while programming and infosecurity almost never do — those two
    # are kept anyway because the user asked for IT curiosity and a thin
    # trickle from them is still the right kind of thing.
    "https://habr.com/ru/rss/best/daily/",
    "https://habr.com/ru/rss/best/weekly/",
    "https://habr.com/ru/rss/hubs/popular_science/articles/",
    "https://habr.com/ru/rss/hubs/physics/articles/",
    "https://habr.com/ru/rss/hubs/astronomy/articles/",
    "https://habr.com/ru/rss/hubs/network_technologies/articles/",
    "https://habr.com/ru/rss/hubs/programming/articles/",
    "https://habr.com/ru/rss/hubs/infosecurity/articles/",
    "https://habr.com/ru/rss/hubs/artificial_intelligence/articles/",
    "https://habr.com/ru/rss/hubs/DIY/articles/",
)

PAUSE_SECONDS = 1.5
"""Habr does not publish a rate limit. This is politeness, not compliance."""

_DIGITS = re.compile(r"\d+")


async def collect(limit: int = 40, session: AsyncSession | None = None) -> list[DiscoveredQuestion]:
    """Everything Habr has to offer, pre-filtered and translated.

    `session` is optional so the collector can be exercised without a database;
    without one the questions come back in Russian and the caller is
    responsible for what that means.
    """
    found: list[DiscoveredQuestion] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": _BROWSER_UA}
    ) as client:
        questions = await _qna(client, limit)
        if not questions:
            # The listing markup changed, or Habr served a challenge page. The
            # feed carries less (no engagement, recency order) but still
            # carries the questions.
            logger.info("habr: qna listings gave nothing, falling back to rss")
            questions = await _qna_rss(client)
        found.extend(questions)

        found.extend(await _articles(client, limit))

    logger.info("habr: %d questions passed the pre-filter", len(found))

    if session is not None and found:
        await _translate(session, found)
    return found


# --- Хабр Q&A ---------------------------------------------------------------


async def _qna(client: httpx.AsyncClient, limit: int) -> list[DiscoveredQuestion]:
    out: list[DiscoveredQuestion] = []
    seen: set[str] = set()

    for index, url in enumerate(QNA_LISTINGS):
        if index:
            await asyncio.sleep(PAUSE_SECONDS)
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug("habr qna %s unavailable: %s", url, exc)
            continue

        for item in _parse_qna_listing(response.text):
            if item.external_id in seen:
                continue
            seen.add(item.external_id)
            out.append(item)
            if len(out) >= limit:
                return out
    return out


def _parse_qna_listing(html: str) -> list[DiscoveredQuestion]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[DiscoveredQuestion] = []

    for node in soup.select("div.question"):
        link = node.select_one("a.question__title-link")
        if link is None:
            continue

        title = link.get_text(strip=True)
        href = str(link.get("href") or "")
        if not title or not href or not looks_like_durable_question(title):
            continue

        out.append(
            DiscoveredQuestion(
                raw_text=title,
                source_name="habr:qna",
                source_url=href,
                external_id=_question_id(href),
                # Answers and followers both mean "somebody besides the asker
                # cared", which is the only thing engagement is used for.
                engagement=_count(node, ".question__answers-count")
                + _count(node, ".question__views-count"),
                observed_at=_published(node),
                original_text=title,
                original_language="ru",
            )
        )
    return out


def _count(node, selector: str) -> int:
    element = node.select_one(selector)
    if element is None:
        return 0
    match = _DIGITS.search(element.get_text(" ", strip=True))
    return int(match.group()) if match else 0


def _published(node) -> datetime:
    element = node.select_one("time.question__date")
    stamp = str(element.get("datetime") or "") if element is not None else ""
    if not stamp:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _question_id(url: str) -> str:
    match = re.search(r"/q/(\d+)", url)
    return match.group(1) if match else url[-64:]


def _rfc822(value: str | None) -> datetime:
    """Parse an RSS date. Both Habr feeds use RFC 822, not ISO 8601."""
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _qna_rss(client: httpx.AsyncClient) -> list[DiscoveredQuestion]:
    """The undocumented feed behind the "Новые вопросы" link.

    Recency order and no engagement figures, so it is strictly the worse
    source — but it is a feed rather than markup, so it is the one more likely
    to still work next month.
    """
    try:
        response = await client.get(QNA_RSS)
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
    except (httpx.HTTPError, ElementTree.ParseError) as exc:
        logger.debug("habr qna rss unavailable: %s", exc)
        return []

    out: list[DiscoveredQuestion] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not looks_like_durable_question(title):
            continue
        out.append(
            DiscoveredQuestion(
                raw_text=title,
                source_name="habr:qna",
                # The feed serves http:// links to an https-only site.
                source_url=link.replace("http://", "https://", 1),
                external_id=_question_id(link),
                engagement=0,
                observed_at=_rfc822(item.findtext("pubDate")),
                original_text=title,
                original_language="ru",
            )
        )
    return out


# --- Habr articles ----------------------------------------------------------


async def _articles(client: httpx.AsyncClient, limit: int) -> list[DiscoveredQuestion]:
    """Article titles that are themselves questions.

    Somebody wrote several thousand words to answer it, and Habr's daily-best
    feed says other people read it — between them that is a stronger signal of
    durable curiosity than most Q&A threads carry.
    """
    out: list[DiscoveredQuestion] = []
    seen: set[str] = set()

    for index, feed in enumerate(ARTICLE_FEEDS):
        if index:
            await asyncio.sleep(PAUSE_SECONDS)
        try:
            response = await client.get(feed)
            response.raise_for_status()
            root = ElementTree.fromstring(response.text)
        except (httpx.HTTPError, ElementTree.ParseError) as exc:
            logger.debug("habr feed %s unavailable: %s", feed, exc)
            continue

        for item in root.findall(".//item"):
            headline = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            # Headline rules, not Q&A rules: most Habr titles are declarative,
            # and the ones that are not put the question wherever it reads best.
            title = question_from_headline(headline)
            if not title or not looks_like_question_headline(title):
                continue

            # Habr appends per-feed utm parameters, so the same article arrives
            # from `best/daily` and from its hub as two different URLs. Strip
            # them before deriving the key, or one article becomes several
            # questions — and the card ends up citing a tracking link.
            canonical = link.split("?", 1)[0].split("#", 1)[0]
            identifier = re.search(r"/(\d+)/?$", canonical)
            key = identifier.group(1) if identifier else canonical
            if key in seen:
                continue
            seen.add(key)

            out.append(
                DiscoveredQuestion(
                    raw_text=title,
                    source_name="habr:articles",
                    source_url=canonical,
                    external_id=key,
                    engagement=0,
                    observed_at=_rfc822(item.findtext("pubDate")),
                    original_text=title,
                    original_language="ru",
                )
            )
            if len(out) >= limit:
                return out
    return out


# --- Translation ------------------------------------------------------------


async def _translate(session: AsyncSession, items: list[DiscoveredQuestion]) -> None:
    """Rewrite `raw_text` in English, in place, keeping the original.

    A failure here is not fatal: the item keeps its Russian `raw_text` and goes
    into the pool as it is. Triage will very likely reject it for being
    unintelligible next to an English corpus, which is the correct outcome —
    quietly dropping the whole harvest because a quota ran out would not be.
    """
    russian = [item for item in items if item.original_language == "ru"]
    if not russian:
        return

    translated = await translation.to_english_many(
        session, [item.original_text for item in russian]
    )

    changed = 0
    for item, english in zip(russian, translated, strict=True):
        english = english.strip()
        if english and english != item.original_text:
            item.raw_text = english
            changed += 1

    logger.info("habr: translated %d/%d questions to english", changed, len(russian))
