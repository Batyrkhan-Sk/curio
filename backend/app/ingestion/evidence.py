"""Evidence retrieval: gather what reliable sources actually say.

Synthesis quality is bounded by this module, not by the model. The rule is
breadth over depth — several independent sources of different kinds beat one
long article, because disagreement between them is the signal the verification
stage looks for.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(20.0)
USER_AGENT = "curio/0.1 (collective-curiosity; evidence retrieval)"

# How much a kind of source is trusted before anything else is known about it.
RELIABILITY = {
    "wikipedia": 0.72,
    "paper": 0.9,
    "gov": 0.88,
    "docs": 0.85,
    "book": 0.8,
    "forum": 0.5,
    "blog": 0.45,
    "video": 0.45,
    "web": 0.4,
}

_TAGS = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class Evidence:
    title: str
    url: str
    publisher: str
    kind: str
    text: str
    reliability: float = 0.5

    def to_source_row(self) -> dict:
        return {
            "title": self.title[:400],
            "url": self.url,
            "publisher": self.publisher[:160],
            "kind": self.kind,
            "reliability": self.reliability,
            "excerpt": self.text[:600],
        }


async def gather(
    question: str,
    *,
    max_items: int = 8,
    queries: list[str] | None = None,
    sites: list[str] | None = None,
) -> list[Evidence]:
    """Collect evidence for a question from several independent places.

    `queries` matters more than it looks. Searching Wikipedia for the literal
    sentence "How can two computers agree on a secret key over an insecure
    connection?" returns nothing useful, because encyclopaedias are indexed by
    topic rather than by question. The caller is expected to pass the topics —
    "Diffie-Hellman key exchange", "public-key cryptography" — and the whole
    quality of the resulting card depends on it.
    """
    terms = queries or [_keywords(question)]
    primary = terms[0]

    tasks: list = [hacker_news_discussion(question)]
    for term in terms[:3]:
        tasks.append(wikipedia(term, limit=1))
    tasks.append(arxiv(primary))
    for site in (sites or ["physics"])[:2]:
        tasks.append(stack_exchange_answers(primary, site=site))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    evidence: list[Evidence] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.debug("evidence source failed: %s", result)
            continue
        evidence.extend(result)

    # Prefer reliable sources, but keep at least one forum voice: forums are
    # where the misconceptions live, and the card has to name them.
    evidence.sort(key=lambda e: e.reliability, reverse=True)
    seen: set[str] = set()
    deduped = []
    for item in evidence:
        if item.url in seen or not item.text.strip():
            continue
        seen.add(item.url)
        deduped.append(item)
    return deduped[:max_items]


_STOPWORDS = {
    "how", "why", "what", "when", "where", "which", "does", "do", "did", "is",
    "are", "was", "were", "can", "could", "would", "should", "the", "a", "an",
    "of", "to", "in", "on", "for", "and", "or", "if", "it", "its", "that",
    "this", "these", "those", "so", "but", "at", "by", "from", "with", "be",
}


def _keywords(question: str) -> str:
    """Crude topic extraction for when no model is available to plan queries."""
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", question.lower())
    kept = [w for w in words if w not in _STOPWORDS and len(w) > 2]
    return " ".join(kept[:6]) or question


def format_for_prompt(evidence: list[Evidence]) -> str:
    blocks = []
    for i, item in enumerate(evidence, start=1):
        blocks.append(
            f"[source {i}] {item.title}\n"
            f"kind: {item.kind} | publisher: {item.publisher} | "
            f"baseline reliability: {item.reliability:.2f}\n"
            f"url: {item.url}\n"
            f"{item.text[:4000]}"
        )
    return "\n\n---\n\n".join(blocks) if blocks else "(no sources retrieved)"


async def wikipedia(query: str, *, limit: int = 2) -> list[Evidence]:
    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        search = await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "format": "json",
            },
        )
        search.raise_for_status()
        titles = [hit["title"] for hit in search.json().get("query", {}).get("search", [])]

        out: list[Evidence] = []
        for title in titles:
            extract = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "prop": "extracts",
                    "titles": title,
                    "explaintext": 1,
                    "exsectionformat": "plain",
                    "format": "json",
                },
            )
            extract.raise_for_status()
            pages = extract.json().get("query", {}).get("pages", {})
            for page in pages.values():
                text = (page.get("extract") or "").strip()
                if not text:
                    continue
                out.append(
                    Evidence(
                        title=page.get("title", title),
                        url="https://en.wikipedia.org/wiki/"
                        + page.get("title", title).replace(" ", "_"),
                        publisher="Wikipedia",
                        kind="wikipedia",
                        text=text[:6000],
                        reliability=RELIABILITY["wikipedia"],
                    )
                )
        return out


async def stack_exchange_answers(
    query: str, *, limit: int = 3, site: str = "physics"
) -> list[Evidence]:
    """Top-voted answers from a topic-appropriate site.

    The site matters: asking the physics site about key exchange returns
    nothing, and the resulting card then fails verification for lack of
    support. The caller picks the site from the question's subject.
    """
    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        response = await client.get(
            "https://api.stackexchange.com/2.3/search/excerpts",
            params={
                "site": site,
                "q": query,
                "order": "desc",
                "sort": "votes",
                "pagesize": limit,
                "answers": 1,
            },
        )
        response.raise_for_status()
        out: list[Evidence] = []
        for item in response.json().get("items", []):
            body = _TAGS.sub("", item.get("excerpt") or "").strip()
            if len(body) < 80:
                continue
            out.append(
                Evidence(
                    title=_TAGS.sub("", item.get("title") or "Stack Exchange answer"),
                    url=f"https://{site}.stackexchange.com/q/{item.get('question_id')}",
                    publisher=f"Stack Exchange · {site}",
                    kind="forum",
                    text=body,
                    reliability=RELIABILITY["forum"] + min(0.2, (item.get("score") or 0) / 200),
                )
            )
        return out


async def hacker_news_discussion(query: str, *, limit: int = 2) -> list[Evidence]:
    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        response = await client.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": query, "tags": "comment", "hitsPerPage": limit * 3},
        )
        response.raise_for_status()
        out: list[Evidence] = []
        for hit in response.json().get("hits", []):
            body = _TAGS.sub("", hit.get("comment_text") or "").strip()
            if len(body) < 200:
                continue
            out.append(
                Evidence(
                    title=hit.get("story_title") or "Hacker News discussion",
                    url=f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                    publisher="Hacker News",
                    kind="forum",
                    text=body[:3000],
                    reliability=RELIABILITY["forum"],
                )
            )
            if len(out) >= limit:
                break
        return out


async def arxiv(query: str, *, limit: int = 2) -> list[Evidence]:
    """Abstracts only — enough to anchor the technical and expert levels."""
    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        response = await client.get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": limit,
                "sortBy": "relevance",
            },
        )
        response.raise_for_status()

    from xml.etree import ElementTree

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError:
        return []

    out: list[Evidence] = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        link = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
        if not summary:
            continue
        out.append(
            Evidence(
                title=re.sub(r"\s+", " ", title),
                url=link,
                publisher="arXiv",
                kind="paper",
                text=re.sub(r"\s+", " ", summary)[:3000],
                reliability=RELIABILITY["paper"],
            )
        )
    return out
