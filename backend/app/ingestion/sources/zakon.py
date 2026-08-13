"""Question discovery from forum.zakon.kz — the Kazakhstan legal-practical forum.

This is the only genuinely Kazakhstan-specific source in the collector set, and
it carries a kind of question the English forums never do: what a person has to
do to get a document, who is liable for what, which deadline applies. Answers
are looked up rather than derived.

Two things about it shape the code:

* **Titles are topics, not questions.** People name a thread after its subject
  — "Возврат товара надлежащего качества" — rather than asking outright.
  Measured on a live section, 2 of 24 rows survived the practical filter. That
  yield is accepted rather than fixed: loosening the filter to catch noun
  phrases would hand the triage model a list of subject headings to pay for.
  Breadth comes from reading many sections instead.
* **Answers here expire.** A rule changes and the card is wrong, which is why
  everything from this source is marked practical downstream rather than
  treated as a durable mechanism.

The forum runs Invision Community, whose listing markup is stable and plain
server-rendered HTML. Like every other collector, this one is not allowed to
raise: a layout change must cost a discovery run its Kazakh questions, not the
whole harvest.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.sources.base import DiscoveredQuestion, looks_like_practical_question
from app.services import translation

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(25.0)
PAUSE_SECONDS = 1.5

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BASE = "https://forum.zakon.kz"

# Sections chosen for how often an ordinary person needs the answer, not for
# how busy they are. Both the id *and* the slug are required: `/forum/124/`
# answers 404, so the slug is not decoration here as it is on many IPS boards.
# Kept as readable Cyrillic and percent-encoded at request time.
SECTIONS: tuple[tuple[int, str, str], ...] = (
    (124, "права-потребителей", "consumer rights"),
    (119, "время-отдыха-отпуск-выходные-праздники", "leave and holidays"),
    (116, "увольнение-прекращение-и-расторжение-трудового-договора", "dismissal"),
    (118, "зарплата-средняя-удержания-премии-надбавки-еткс", "pay and deductions"),
    (
        122,
        "больничные-беременность-и-роды-иные-гарантии-и-компенсации",
        "sick leave and maternity",
    ),
    (
        127,
        "жилищные-отношения-коммуналка-землепользование-строительство-"
        "регистрация-прав-на-недвижимость",
        "housing and utilities",
    ),
    (131, "здравоохранение-физкультура-и-спорт", "healthcare"),
    (130, "образование-наука-культура", "education"),
    (
        115,
        "заключение-трудового-договора-прием-на-работу-испытательный-срок",
        "hiring and contracts",
    ),
    (120, "командировки", "business travel"),
)

_TOPIC_HREF = re.compile(r"/topic/(\d+)-")


def _parse_listing(html: str) -> list[tuple[str, str, str]]:
    """Return (topic_id, title, url) for every topic row on a section page."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[tuple[str, str, str]] = []

    for anchor in soup.select('h4.ipsDataItem_title a[href*="/topic/"]'):
        href = anchor.get("href") or ""
        match = _TOPIC_HREF.search(href)
        if not match:
            continue
        # The same heading carries the "jump to page 3" links, whose text is
        # the page number. They match the selector and are not topics.
        if "page=" in href or "?do=" in href:
            continue
        title = " ".join(anchor.get_text(strip=True).split())
        if len(title) < 10:
            continue
        rows.append((match.group(1), title, href))
    return rows


async def _section(
    client: httpx.AsyncClient, forum_id: int, slug: str, label: str
) -> list[DiscoveredQuestion]:
    url = f"{BASE}/forum/{forum_id}-{quote(slug)}/"
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.debug("zakon section %s unavailable: %s", forum_id, exc)
        return []

    out: list[DiscoveredQuestion] = []
    seen: set[str] = set()

    for topic_id, title, href in _parse_listing(response.text):
        if topic_id in seen:
            continue
        seen.add(topic_id)
        if not looks_like_practical_question(title):
            continue
        out.append(
            DiscoveredQuestion(
                raw_text=title,  # replaced by the translation below
                source_name="zakon.kz",
                source_url=href,
                external_id=f"zakon:{topic_id}",
                original_text=title,
                original_language="ru",
            )
        )

    logger.debug("zakon %s (%s): %d kept", forum_id, label, len(out))
    return out


async def collect(limit: int = 40, session: AsyncSession | None = None) -> list[DiscoveredQuestion]:
    """Practical Kazakh questions, pre-filtered and translated.

    `session` is optional so the collector can be exercised without a database.
    Without one the questions come back in Russian, which no downstream stage
    is prepared for — the index, the embeddings and both prompts are English.
    """
    found: list[DiscoveredQuestion] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": _BROWSER_UA}
    ) as client:
        for index, (forum_id, slug, label) in enumerate(SECTIONS):
            if index:
                await asyncio.sleep(PAUSE_SECONDS)
            found.extend(await _section(client, forum_id, slug, label))
            if len(found) >= limit:
                found = found[:limit]
                break

    logger.info("zakon: %d questions passed the practical filter", len(found))

    if session is not None and found:
        await _translate(session, found)
    return found


async def _translate(session: AsyncSession, items: list[DiscoveredQuestion]) -> None:
    """Put the English form in `raw_text`, keeping the Russian in `original_text`.

    A failed translation drops the question rather than letting Russian into an
    English pool, where it would match nothing and duplicate everything.
    """
    if not translation.enabled():
        logger.info("zakon: translation unavailable, dropping %d questions", len(items))
        items.clear()
        return

    originals = [item.original_text for item in items]
    try:
        english = await translation.to_english_many(session, originals)
    except Exception as exc:  # noqa: BLE001 — a dead translator must not end the run
        logger.warning("zakon: translation failed, dropping harvest: %s", exc)
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
