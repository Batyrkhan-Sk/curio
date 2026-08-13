"""Question discovery from public forum APIs.

All endpoints used here are public and unauthenticated. Each collector is
independently failable: one source being down or rate-limited must never stop
a discovery run, so every one of them swallows its own errors and returns an
empty list.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from xml.etree import ElementTree

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion.sources import habr, telegram_channels, threads, zakon
from app.ingestion.sources.base import DiscoveredQuestion, looks_like_durable_question

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(20.0)

REDDIT_PAUSE_SECONDS = 6.0
REDDIT_RETRIES = 4

# Reddit serves its Atom feeds to ordinary browser agents and blocks the polite
# project-identifying one, so the fallback transport has to look like a browser.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

REDDIT_SUBS = [
    "explainlikeimfive",
    "askscience",
    "askengineers",
    "NoStupidQuestions",
    "todayilearned",
    "AskHistorians",
    "askmath",
    "AskComputerScience",
    "askphysics",
    "AskBiology",
    "askchemistry",
    "AskEconomics",
    "answers",
    # Practically useful curiosity — the questions whose answers change what
    # someone does, rather than only what they find interesting.
    "LifeProTips",
    "personalfinance",
    "Frugal",
    "HomeImprovement",
    "AskCulinary",
]

STACKEXCHANGE_SITES = [
    "stackoverflow",
    "physics",
    "engineering",
    "aviation",
    "electronics",
    "softwareengineering",
    "security",
    "earthscience",
    "chemistry",
    "biology",
    "math",
    "economics",
    "cooking",
    "money",
    "diy",
    "outdoors",
]


async def collect_all(
    limit_per_source: int = 40, session: AsyncSession | None = None
) -> list[DiscoveredQuestion]:
    """Run every collector and return the combined, pre-filtered harvest.

    `session` is only needed by sources that are not in English — Habr uses it
    to translate what it finds, and to reach the translation cache so a
    question seen last week is not paid for twice.
    """
    collectors = (
        ("hackernews", hacker_news(limit_per_source)),
        ("reddit", reddit(limit_per_source)),
        ("stackexchange", stack_exchange(limit_per_source)),
        ("habr", habr.collect(limit_per_source, session=session)),
        ("zakon", zakon.collect(limit_per_source, session=session)),
        ("threads", threads.collect(limit_per_source, session=session)),
        ("telegram", telegram_channels.collect(limit_per_source, session=session)),
    )
    found: list[DiscoveredQuestion] = []
    for name, coro in collectors:
        try:
            items = await coro
            logger.info("discovery: %s returned %d questions", name, len(items))
            found.extend(items)
        except Exception as exc:
            logger.warning("discovery: %s failed: %s", name, exc)
    return found


async def hacker_news(limit: int = 40) -> list[DiscoveredQuestion]:
    """Ask HN threads and question-shaped submissions via the Algolia index."""
    out: list[DiscoveredQuestion] = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for query in ("why", "how does", "ask hn why"):
            response = await client.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": query,
                    "tags": "story",
                    "hitsPerPage": limit,
                    "numericFilters": "points>20",
                },
            )
            response.raise_for_status()
            for hit in response.json().get("hits", []):
                title = (hit.get("title") or "").strip()
                if not title or not looks_like_durable_question(title):
                    continue
                out.append(
                    DiscoveredQuestion(
                        raw_text=title,
                        source_name="hackernews",
                        source_url=f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                        external_id=str(hit.get("objectID")),
                        engagement=int(hit.get("points") or 0)
                        + int(hit.get("num_comments") or 0),
                        observed_at=_parse_iso(hit.get("created_at")),
                    )
                )
    return out


async def reddit(limit: int = 40) -> list[DiscoveredQuestion]:
    """Top posts from question-shaped subreddits.

    Three transports, in order of how much they carry. With credentials the
    authenticated API gives 100 requests a minute plus scores and comment
    counts. Without them the anonymous JSON endpoint is tried, though Reddit
    now answers it with a 403 block page from most datacentre addresses, and
    the last resort is the Atom feed: no scores, aggressively throttled, but
    still serving the question text, which is the part that matters.
    """
    token = await _reddit_token() if settings.reddit_oauth_enabled else None
    out: list[DiscoveredQuestion] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": _BROWSER_UA}
    ) as client:
        for index, sub in enumerate(REDDIT_SUBS):
            # Reddit throttles hard on consecutive anonymous requests and
            # answers 429 with an empty body, so unauthenticated runs are paced.
            # An authenticated run has a real per-minute budget and does not
            # need the delay.
            if index and token is None:
                await asyncio.sleep(REDDIT_PAUSE_SECONDS)
            items = await _reddit_json(client, sub, limit, token=token)
            if items is None:
                items = await _reddit_rss(client, sub)
            out.extend(items or [])

    logger.info(
        "reddit: %d questions from %d subreddits (%s)",
        len(out),
        len(REDDIT_SUBS),
        "authenticated" if token else "anonymous",
    )
    return out


async def _reddit_token() -> str | None:
    """Client-credentials token for a script-type app. None if it cannot be had."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(settings.reddit_client_id, settings.reddit_client_secret),
                headers={"User-Agent": settings.reddit_user_agent},
            )
            response.raise_for_status()
            return response.json().get("access_token")
    except (httpx.HTTPError, ValueError) as exc:
        # Credentials being wrong must not stop the run; the anonymous
        # transports still work, just less well.
        logger.warning("reddit: authentication failed, falling back: %s", exc)
        return None


async def _reddit_json(
    client: httpx.AsyncClient, sub: str, limit: int, *, token: str | None = None
) -> list[DiscoveredQuestion] | None:
    """None means the transport failed; an empty list means it returned nothing."""
    host = "oauth.reddit.com" if token else "www.reddit.com"
    headers = {"User-Agent": settings.reddit_user_agent}
    if token:
        headers["Authorization"] = f"bearer {token}"

    try:
        response = await client.get(
            f"https://{host}/r/{sub}/top{'' if token else '.json'}",
            params={"t": "week", "limit": min(limit, 100)},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("reddit json r/%s unavailable: %s", sub, exc)
        return None

    out: list[DiscoveredQuestion] = []
    for child in payload.get("data", {}).get("children", []):
        data = child.get("data", {})
        title = (data.get("title") or "").strip()
        if not title or not looks_like_durable_question(title):
            continue
        out.append(
            DiscoveredQuestion(
                raw_text=title,
                source_name=f"reddit:{sub}",
                source_url=f"https://www.reddit.com{data.get('permalink', '')}",
                external_id=str(data.get("id")),
                engagement=int(data.get("score") or 0)
                + int(data.get("num_comments") or 0),
                observed_at=datetime.fromtimestamp(
                    data.get("created_utc") or 0, tz=timezone.utc
                ),
            )
        )
    return out


async def _reddit_rss(client: httpx.AsyncClient, sub: str) -> list[DiscoveredQuestion]:
    """Fetch one subreddit's Atom feed, retrying through Reddit's throttling.

    Reddit answers an exhausted budget with a bare 429 — no Retry-After header
    and no body — and refills it erratically, so a fixed pause is not enough
    and success is partly luck. Retrying a few times with a growing wait turns
    a single-subreddit harvest into most of the list.
    """
    root = None
    for attempt in range(REDDIT_RETRIES):
        if attempt:
            await asyncio.sleep(REDDIT_PAUSE_SECONDS * (attempt + 1))
        try:
            response = await client.get(
                f"https://www.reddit.com/r/{sub}/top/.rss", params={"t": "week"}
            )
            if response.status_code == 429:
                continue
            response.raise_for_status()
            root = ElementTree.fromstring(response.text)
            break
        except (httpx.HTTPError, ElementTree.ParseError) as exc:
            logger.debug("reddit rss r/%s unavailable: %s", sub, exc)
            return []

    if root is None:
        logger.debug("reddit rss r/%s throttled after %d attempts", sub, REDDIT_RETRIES)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    out: list[DiscoveredQuestion] = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        if not title or not looks_like_durable_question(title):
            continue
        link_el = entry.find("atom:link", ns)
        out.append(
            DiscoveredQuestion(
                raw_text=title,
                source_name=f"reddit:{sub}",
                source_url=(link_el.get("href") if link_el is not None else "") or "",
                external_id=(
                    entry.findtext("atom:id", default="", namespaces=ns) or ""
                ).removeprefix("t3_"),
                # The Atom feed carries no score. Ranking still works because a
                # question observed in several places accumulates engagement
                # through the dedupe merge.
                engagement=0,
                observed_at=_parse_iso(
                    entry.findtext("atom:updated", default=None, namespaces=ns)
                ),
            )
        )
    return out


async def stack_exchange(limit: int = 40) -> list[DiscoveredQuestion]:
    """Highly-voted conceptual questions across Stack Exchange sites."""
    out: list[DiscoveredQuestion] = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for site in STACKEXCHANGE_SITES:
            try:
                response = await client.get(
                    "https://api.stackexchange.com/2.3/questions",
                    params={
                        "site": site,
                        "order": "desc",
                        "sort": "votes",
                        "pagesize": min(limit, 100),
                        "filter": "default",
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.debug("stackexchange %s unavailable: %s", site, exc)
                continue

            payload = response.json()
            for item in payload.get("items", []):
                title = (item.get("title") or "").strip()
                if not title or not looks_like_durable_question(title):
                    continue
                out.append(
                    DiscoveredQuestion(
                        raw_text=title,
                        source_name=f"stackexchange:{site}",
                        source_url=item.get("link", ""),
                        external_id=str(item.get("question_id")),
                        engagement=int(item.get("score") or 0)
                        + int(item.get("answer_count") or 0),
                        observed_at=datetime.fromtimestamp(
                            item.get("creation_date") or 0, tz=timezone.utc
                        ),
                    )
                )
            if payload.get("quota_remaining", 1) < 20:
                logger.info("stackexchange quota nearly exhausted, stopping early")
                break
    return out


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
