"""Question discovery from Threads, via the rendering worker.

Threads is not a forum and does not behave like one. Three things measured on
live tag pages shape everything here:

* **The tag decides the yield.** Place tags are where people arrange to meet:
  130 posts under #Казахстан, #Алматы and #Астана produced zero usable
  questions. The question-word tags are a different population entirely —
  #почему was 16 question sentences out of 17 posts. So the tag list is the
  single most important thing in this module, and it is all curiosity.
* **Posts are prose, not titles.** A forum hands over one question per row.
  A Threads post is a paragraph with a question somewhere inside it, so the
  question has to be cut out of the sentence it arrived in.
* **Nothing here is curated.** The filter the English forums share is
  deliberately permissive because those communities have already done the
  filtering. Threads has not: "Why's she so damn cute?" passes every general
  test there is. Hence the extra bar below, which exists for this source
  alone.

The browser lives in a separate service — see `backend/workers/threads` for
why. If that service is down this collector returns nothing, like every other
collector that cannot reach its source.
"""

from __future__ import annotations

import logging
import re

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion.sources.base import (
    DiscoveredQuestion,
    is_cyrillic,
    looks_like_question_headline,
)
from app.services import translation

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(900.0)
"""The worker renders a browser page per tag and scrolls each one. Twenty-two
tags at ~15s each overran a 180s timeout, and the failure is silent in a
misleading way: httpx raises ReadTimeout with an empty message, so the log
said "worker unreachable" about a worker that was working perfectly."""

# Curiosity tags only. See the module docstring for the measurement that put
# every place name off this list.
DEFAULT_TAGS: tuple[str, ...] = (
    # Question words first — these are the highest-yielding tags by a wide
    # margin, because a post tagged #почему is usually asking something.
    "почему",
    "why",
    "howitworks",
    "howdoesitwork",
    "howthingswork",
    "whyisit",
    # Subject tags. Lower question rate, but what does come through is more
    # often about a mechanism than the question-word tags are.
    "science",
    "curiosity",
    "didyouknow",
    "explainlikeimfive",
    "engineering",
    "spacefacts",
    "physics",
    "biology",
    "chemistry",
    "astronomy",
    "technology",
    "psychologyfacts",
    "funfacts",
    "sciencefacts",
    "какустроено",
    "интересныефакты",
)

# A post is prose, so the split is on every sentence end, not only on "?".
# Breaking on question marks alone leaves whatever preceded the question glued
# to its front — "Random thought. Ever wonder why some trains…" — and that
# sentence would go on to become the card title.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# An English question cue anywhere in the line. Threads is global and the
# harvest came back in Thai, Hindi, Tagalog and Malay; the pipeline reads
# English and translates Russian, and a question in neither matches nothing
# downstream. Latin script alone does not mean English — "Kasi alam mong
# tatanggapin kita?" is Latin, is a question, and is not one of ours.
_EN_QUESTION_ANYWHERE = re.compile(
    r"\b(why|how|what|when|where|which|who|does|do|did|is|are|can|could|"
    r"would|should|must)\b",
    re.IGNORECASE,
)

# Social noise that every general filter lets through, because on a forum it
# would not exist. A durable question is about the world, and the world is not
# "she".
_SOCIAL = re.compile(
    r"\b(she|he|her|him|hers|his)\b"
    r"|\b(lately|rn|tbh|fr fr|lol|lmao)\b"
    r"|\b(am i|are we|are you) the only\b"
    # "Did you know…?" and "Do you know what this is?" are engagement hooks
    # wearing a question mark. The answer is yes or no, and the card would be
    # written about whatever followed rather than about the question.
    r"|^\s*(do|did|does) (you|u|anyone|anybody) know\b"
    r"|^\s*(so|and|but|like)\b",
    re.IGNORECASE,
)

MIN_LENGTH = 25
"""Below this a Threads question is nearly always a reaction: "Why's it
ghetto?", "Get it?", "Are you home?". Forum titles have no such floor because
a forum title is written to be understood alone."""


def question_sentences(post: str) -> list[str]:
    """Cut the interrogative sentences out of a post."""
    return [
        part.strip()
        for part in _SENTENCE_SPLIT.split(post or "")
        if part.strip().endswith("?")
    ]


def is_usable(text: str) -> bool:
    """The extra bar Threads needs on top of the shared headline filter."""
    stripped = text.strip()
    if len(stripped) < MIN_LENGTH:
        return False
    if _SOCIAL.search(stripped):
        return False
    if not is_cyrillic(stripped) and not _EN_QUESTION_ANYWHERE.search(stripped):
        return False
    return looks_like_question_headline(stripped)


async def collect(
    limit: int = 40, session: AsyncSession | None = None
) -> list[DiscoveredQuestion]:
    """Ask the worker for posts, and return the questions inside them."""
    if not settings.threads_enabled:
        return []
    if not settings.threads_worker_url:
        logger.info("threads: no worker url configured")
        return []

    tags = list(settings.threads_tags or DEFAULT_TAGS)
    payload = {"tags": tags, "profiles": [], "limit_per_tag": max(limit, 20)}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                f"{settings.threads_worker_url.rstrip('/')}/harvest", json=payload
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # `exc` is routinely empty (ReadTimeout), so the class name carries the
        # only information there is about what went wrong.
        logger.warning("threads: worker call failed: %s %s", exc.__class__.__name__, exc)
        return []

    if body.get("failures"):
        logger.info("threads: %s", body["failures"])

    found: list[DiscoveredQuestion] = []
    seen: set[str] = set()

    for post in body.get("posts", []):
        text = post.get("text") or ""
        for sentence in question_sentences(text):
            if sentence in seen or not is_usable(sentence):
                continue
            seen.add(sentence)
            russian = is_cyrillic(sentence)
            found.append(
                DiscoveredQuestion(
                    raw_text=sentence,
                    source_name="threads",
                    source_url=post.get("url") or "",
                    # A post can hold more than one question, so the post id
                    # alone would collide and the pool would keep one of them.
                    external_id=f"{post.get('external_id') or 'threads'}:{len(seen)}",
                    engagement=int(post.get("engagement") or 0),
                    original_text=sentence if russian else "",
                    original_language="ru" if russian else "",
                )
            )
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break

    logger.info("threads: %d questions passed the filter", len(found))

    if session is not None and found:
        await _translate(session, found)
    return found


async def _translate(session: AsyncSession, items: list[DiscoveredQuestion]) -> None:
    """Translate the Russian ones in place, leaving the English alone.

    Unlike the Habr and zakon collectors this harvest is mixed, so translating
    the whole batch would send English through the model to get English back.
    """
    russian = [item for item in items if item.original_language == "ru"]
    if not russian:
        return

    if not translation.enabled():
        logger.info("threads: no translator, dropping %d russian questions", len(russian))
        items[:] = [item for item in items if item.original_language != "ru"]
        return

    try:
        english = await translation.to_english_many(
            session, [item.original_text for item in russian]
        )
    except Exception as exc:  # noqa: BLE001 — a dead translator must not end the run
        logger.warning("threads: translation failed, dropping russian: %s", exc)
        items[:] = [item for item in items if item.original_language != "ru"]
        return

    failed = set()
    for item, text in zip(russian, english):
        cleaned = (text or "").strip()
        if not cleaned or cleaned == item.original_text:
            failed.add(id(item))
            continue
        item.raw_text = cleaned

    if failed:
        items[:] = [item for item in items if id(item) not in failed]
