"""Pictures for cards, and the rules for when a card should not have one.

A knowledge card is prose. An image on it has to earn its place: either it is
the thing the question points at, or it is nothing. So the default is no
image, and three gates stand between a candidate and a card.

  1. **Provenance.** Only two origins are trusted, and both are already cited
     by the card. The lead image of a Wikipedia article the card was actually
     built from, and the picture attached to the forum post where the question
     was asked. Nothing is searched for, and nothing is generated: an invented
     illustration would be the one element on a card that no source stands
     behind, which is the opposite of what the card is for.

  2. **Shape.** The filters below are cheap, so they run first. Logos, flags,
     coats of arms, signatures, icons and anything too small to read are never
     useful whatever the question was, and they are dropped before a model is
     asked to think about them.

  3. **Judgement.** Whatever survives is offered to the synthesis model as a
     numbered list, and the model picks the one that helps a reader — or none,
     which is the expected answer for most cards. See `ai/prompts.py`.

That third gate is the one that matters. A portrait of Whitfield Diffie is a
real photograph, correctly licensed, and genuinely from a source the key
exchange card cites. It also explains nothing whatsoever, and no rule short of
reading the question can tell you that.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass, fields
from typing import Any

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "curio/0.1 (collective-curiosity; image retrieval)"
"""Wikimedia asks projects to identify themselves, and Openverse rate-limits
anonymous clients more tightly than named ones."""

MIN_EDGE = 320
"""Below this on either edge a picture is a thumbnail, not an illustration."""

MAX_ASPECT = 4.0
"""Banners and panoramas do not survive being laid out in a column of prose."""


@dataclass(slots=True)
class ImageCandidate:
    """One picture that could go on a card, with everything needed to credit it."""

    url: str
    provider: str
    """'wikimedia' or 'reddit' — decides the fetch headers in the media proxy."""

    source_url: str = ""
    """The page this belongs to: the article, or the post the question came from."""

    title: str = ""
    credit: str = ""
    license: str = ""
    license_url: str = ""
    width: int = 0
    height: int = 0

    origin: str = "evidence"
    """'question' when the asker attached it, 'evidence' when a source did.

    The distinction is editorial rather than technical. A picture from the post
    is part of the question — often it *is* the question — so it is offered to
    the model first and described as such."""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "ImageCandidate | None":
        """Rebuild one from a stored row, tolerating a row written by an older
        version of this dataclass. Unknown keys are dropped and missing ones
        take their defaults, so adding a field here never strands existing
        questions with an unreadable image."""
        if not data or not data.get("url"):
            return None
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


# --- Shape gate -------------------------------------------------------------

# Matched against the file or post title. Every one of these is a symbol or a
# piece of page furniture: it depicts a thing's identity rather than the thing,
# so it cannot illustrate how anything works.
_JUNK_TITLE = re.compile(
    r"\b(logo|wordmark|icon|favicon|banner|flag|coat[ _-]?of[ _-]?arms|crest|"
    r"seal|emblem|signature|barnstar|stub|placeholder|blank|no[ _-]?image|"
    r"question[ _-]?(mark|book)|padlock|edit[ _-]?icon|commons[ _-]?logo|"
    r"wiki(pedia|media|source|quote|[ _-]letter)|ambox|symbol|pictogram|"
    r"location[ _-]?map|locator|orthographic[ _-]?projection|"
    # The rest of Wikipedia's maintenance furniture, which `generator=images`
    # returns as ordinary files indistinguishable from content. Every one of
    # these was observed on a real article during testing.
    r"nuvola|portal[ _-]?puzzle|disambig\w*|magnify[ _-]?clip|"
    r"folder[ _-]?hexagonal|text[ _-]?document|red[ _-]?(x|check))\b",
    re.IGNORECASE,
)

# Formats Telegram will not render in a link preview, and that an <img> handles
# only unevenly. This is checked against the URL actually stored, which is
# always a *rendered* one — MediaWiki rasterises an SVG to PNG when asked for a
# thumbnail width, so the best diagrams on Wikipedia (which are nearly all SVG)
# reach a card as PNG and never meet this filter. What it still catches is a
# provider handing over an original: an animation, a scanned TIFF, a PDF.
_BAD_EXTENSION = re.compile(r"\.(svg|ogv|webm|gif|tif|tiff|pdf|djvu)(\?|$)", re.IGNORECASE)

_ALLOWED_HOSTS = {
    "upload.wikimedia.org",
    "i.redd.it",
    "preview.redd.it",
    "external-preview.redd.it",
    # Openverse aggregates dozens of providers on as many hosts, which an
    # allowlist cannot track. Its own thumbnail endpoint collapses them all to
    # one address, so that is what gets stored for anything it finds off
    # Wikimedia — see `_openverse_source`.
    "api.openverse.org",
}
"""The only hosts the media proxy will fetch from.

An allowlist rather than a scheme check, because the proxy takes its URL from
a database row that ingestion wrote, and ingestion takes it from a third party.
Without this, anything that can get a string into that row can make the server
issue arbitrary requests from inside the network."""


def allowed_host(url: str) -> bool:
    try:
        host = httpx.URL(url).host
    except (httpx.InvalidURL, UnicodeError, ValueError):
        return False
    return host in _ALLOWED_HOSTS


def usable(candidate: ImageCandidate | None) -> bool:
    """The cheap gate. True means 'worth a model's attention', not 'use this'."""
    if candidate is None or not candidate.url:
        return False
    if not candidate.url.startswith("https://") or not allowed_host(candidate.url):
        return False
    if _BAD_EXTENSION.search(candidate.url):
        return False
    if _JUNK_TITLE.search(candidate.title or ""):
        return False

    # Dimensions are advisory: Reddit always reports them, Wikimedia usually
    # does, and a missing value must not be read as zero and rejected.
    width, height = candidate.width, candidate.height
    if width and height:
        if min(width, height) < MIN_EDGE:
            return False
        if max(width, height) / min(width, height) > MAX_ASPECT:
            return False
    return True


def describe_for_prompt(candidates: list[ImageCandidate]) -> str:
    """Render the candidate list the model chooses from.

    Deliberately spare. The model is told what the picture is *of* and where it
    came from, and nothing about how much work went into finding it — the
    likeliest correct answer is `null` and the prompt must not make that feel
    like a failure.
    """
    lines = []
    for index, item in enumerate(candidates):
        where = (
            "attached to the post where the question was asked"
            if item.origin == "question"
            else f"lead image of the source article ({item.source_url})"
        )
        caption = item.title.strip() or "(untitled)"
        lines.append(f"[image {index}] {caption} — {where}")
    return "\n".join(lines)


# --- Wikimedia --------------------------------------------------------------

_API = "https://en.wikipedia.org/w/api.php"

_WIKI_GATE = asyncio.Semaphore(1)
"""Serialises image lookups against MediaWiki.

Synthesising one card already costs Wikipedia several requests from
`evidence.gather`, and the image collectors add a lead-image pair plus an
article-images call on top. Fired concurrently — which is the natural shape,
since everything else here fans out — that is enough to draw a 429, and a
throttled run silently produces cards with no pictures.

One at a time is not a meaningful slowdown: these run while the evidence for
the same card is being fetched, so they overlap with work that has to happen
anyway."""

_HTML_TAGS = re.compile(r"<[^>]+>")


def _plain(value: Any) -> str:
    """extmetadata values arrive as HTML fragments with links in them."""
    text = _HTML_TAGS.sub("", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


async def _query(
    client: httpx.AsyncClient, params: dict[str, Any], *, what: str
) -> dict[str, Any] | None:
    """One MediaWiki call, with the throttling handled loudly.

    A 429 arrives as an HTML error page, so parsing it as JSON raises rather
    than returning a recognisable error, and the obvious `except` swallows it
    into `None` — which is indistinguishable from "this article has no
    picture". A run that trips the rate limit then produces cards with no
    images and says nothing about why, which is how you conclude the feature
    does not work when in fact it was never allowed to ask.

    So throttling is retried once, and if it persists it is logged as a
    warning rather than at debug: an image that is missing because nobody
    looked is a different fact from an image that does not exist.
    """
    for attempt in range(2):
        try:
            async with _WIKI_GATE:
                response = await client.get(_API, params=params)
        except httpx.HTTPError as exc:
            logger.debug("wikipedia %s request failed: %s", what, exc)
            return None

        if response.status_code == 429:
            if attempt == 0:
                await asyncio.sleep(1.5)
                continue
            logger.warning("wikipedia rate-limited the %s lookup; no image found", what)
            return None

        if response.status_code != 200:
            logger.debug("wikipedia %s returned %d", what, response.status_code)
            return None

        try:
            return response.json()
        except ValueError:
            logger.warning("wikipedia %s returned a non-JSON body", what)
            return None
    return None


async def wikipedia_lead_image(
    client: httpx.AsyncClient, title: str
) -> ImageCandidate | None:
    """The lead image of one article, with its licence and author.

    Two calls, and the second is not optional. Wikimedia hosts plenty of images
    that are free to use only if attributed, so a card that shows one without
    naming the author is not using a free image — it is using someone's work
    without the one thing they asked for. If the licence cannot be read, the
    picture is dropped.
    """
    payload = await _query(
        client,
        {
            "action": "query",
            "prop": "pageimages",
            "titles": title,
            # `original` can be a 40MB TIFF scan; the 1024px thumbnail is what
            # any of the three surfaces would have downscaled to anyway.
            "piprop": "thumbnail|name",
            "pithumbsize": 1024,
            "format": "json",
        },
        what=f"lead image for {title!r}",
    )
    if payload is None:
        return None
    pages = payload.get("query", {}).get("pages", {})

    thumbnail: dict[str, Any] | None = None
    file_name = ""
    for page in pages.values():
        thumbnail = page.get("thumbnail")
        file_name = page.get("pageimage") or ""
        if thumbnail:
            break

    if not thumbnail or not thumbnail.get("source") or not file_name:
        return None

    candidate = ImageCandidate(
        url=str(thumbnail["source"]),
        provider="wikimedia",
        source_url="https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
        title=file_name.rsplit(".", 1)[0].replace("_", " "),
        width=int(thumbnail.get("width") or 0),
        height=int(thumbnail.get("height") or 0),
    )
    # Cheap rejections happen before spending the second request on licensing.
    if not usable(candidate):
        return None

    meta = await _query(
        client,
        {
            "action": "query",
            "prop": "imageinfo",
            "titles": f"File:{file_name}",
            "iiprop": "extmetadata",
            "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|ImageDescription",
            "format": "json",
        },
        what=f"licence for {file_name!r}",
    )
    if meta is None:
        return None
    meta_pages = meta.get("query", {}).get("pages", {})

    extra: dict[str, Any] = {}
    for page in meta_pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        extra = info.get("extmetadata") or {}
        if extra:
            break

    licence = _plain((extra.get("LicenseShortName") or {}).get("value"))
    if not licence:
        return None

    candidate.license = licence[:80]
    candidate.license_url = _plain((extra.get("LicenseUrl") or {}).get("value"))[:300]
    candidate.credit = _plain((extra.get("Artist") or {}).get("value"))[:200]

    # The file's own description beats a name derived from the filename, which
    # is often a camera serial number.
    description = _plain((extra.get("ImageDescription") or {}).get("value"))
    if 8 < len(description) < 200:
        candidate.title = description

    # Re-checked because the description just replaced the title the first
    # check ran against, and "SVG logo of ..." arrives that way.
    return candidate if usable(candidate) else None


async def wikipedia_article_images(
    client: httpx.AsyncClient, title: str, *, limit: int = 3
) -> list[ImageCandidate]:
    """Explanatory images from the *body* of an article, not just its lead.

    The lead image answers "what does this look like", which is the wrong
    question for most cards. The diagram that answers "how does this work"
    is usually further down: the TLS article leads with a screenshot of a
    browser padlock and carries a full handshake sequence diagram below it.

    Everything comes back in one call — `generator=images` walks the files on
    the page while `prop=imageinfo` describes each — and `iiurlwidth` is what
    makes it usable, because it returns a rendered thumbnail. Wikipedia's
    diagrams are almost all SVG, which Telegram will not preview and browsers
    render inconsistently at arbitrary sizes; asking for a width hands back a
    PNG of it instead.
    """
    payload = await _query(
        client,
        {
            "action": "query",
            "generator": "images",
            "titles": title,
            # Articles routinely carry a dozen files, most of them furniture.
            # Twenty is enough to reach the real diagrams without paging.
            "gimlimit": 20,
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|ImageDescription",
            "iiurlwidth": 1024,
            "format": "json",
        },
        what=f"article images for {title!r}",
    )
    if payload is None:
        return []

    article_url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
    out: list[ImageCandidate] = []

    for page in payload.get("query", {}).get("pages", {}).values():
        if len(out) >= limit:
            break
        info = (page.get("imageinfo") or [{}])[0]
        served = info.get("thumburl") or info.get("url") or ""
        if not served:
            continue

        extra = info.get("extmetadata") or {}
        licence = _plain((extra.get("LicenseShortName") or {}).get("value"))
        if not licence:
            # No readable licence, no picture. Same rule as the lead image.
            continue

        # `File:Full TLS 1.2 Handshake.svg` -> `Full TLS 1.2 Handshake`. The
        # description is preferred when there is one, as for the lead image.
        name = str(page.get("title", "")).removeprefix("File:").rsplit(".", 1)[0]
        description = _plain((extra.get("ImageDescription") or {}).get("value"))

        candidate = ImageCandidate(
            url=served,
            provider="wikimedia",
            source_url=article_url,
            title=(description if 8 < len(description) < 200 else name.replace("_", " ")),
            credit=_plain((extra.get("Artist") or {}).get("value"))[:200],
            license=licence[:80],
            license_url=_plain((extra.get("LicenseUrl") or {}).get("value"))[:300],
            width=int(info.get("thumbwidth") or 0),
            height=int(info.get("thumbheight") or 0),
        )
        # The junk filter earns its keep here: every article carries the Commons
        # logo and the "this needs citations" question-book icon as real files.
        if usable(candidate) and not _JUNK_TITLE.search(name):
            out.append(candidate)

    return out


# --- Openverse --------------------------------------------------------------

_OPENVERSE = "https://api.openverse.org/v1/images/"

_RELEVANCE_STOPWORDS = {"the", "a", "an", "of", "in", "and", "or", "to"}


def _mentions_topic(item: dict[str, Any], query: str) -> bool:
    """Does this result actually claim to be about the thing we searched for?

    Openverse always returns its best matches, and on a technical query its
    best is often unrelated — searching "Transport Layer Security" offered a
    photograph of Kanazawa Castle. Passing that to the model is worse than
    passing nothing: it is asked to choose from a list where the honest answer
    is "none of these", and a long list of near-misses is exactly what tempts a
    model into picking one.

    So a result has to earn its place by naming at least one substantial word
    from the query in its title or tags. Crude, and it drops the occasional
    good picture filed under a synonym — an acceptable trade when the
    alternative is polluting the choice.
    """
    words = {
        w for w in re.findall(r"[a-z0-9]+", query.lower())
        if len(w) > 3 and w not in _RELEVANCE_STOPWORDS
    }
    if not words:
        return True

    haystack = str(item.get("title") or "").lower()
    haystack += " " + " ".join(
        str(tag.get("name", "")).lower() for tag in (item.get("tags") or [])
    )
    return any(word in haystack for word in words)


def _openverse_source(item: dict[str, Any]) -> str:
    """Pick the URL to store for one Openverse result.

    Two paths, because Openverse's own thumbnail service is a proxy that
    sometimes fails on upstreams it cannot fetch — observed 424ing on exactly
    the Wikimedia-hosted results. When the original already sits on a host the
    proxy trusts, it is fetched directly and the flaky hop is skipped; only the
    rest (Flickr, museums, everything else) go through the thumbnail endpoint,
    which is also what keeps them inside a one-line allowlist.
    """
    direct = str(item.get("url") or "")
    if allowed_host(direct) and not _BAD_EXTENSION.search(direct):
        return direct
    return str(item.get("thumbnail") or "")


async def _renders(client: httpx.AsyncClient, url: str) -> bool:
    """Confirm a URL actually returns image bytes before a card commits to it.

    Only Openverse needs this. Its thumbnail endpoint is a proxy over upstreams
    it does not control, and it answers with a JSON error rather than an image
    when one of them refuses — so a candidate can look perfectly well-formed,
    be stored, and then 502 the first time a reader opens the card. Wikimedia
    and Reddit serve their own files and are checked by nothing.

    A ranged request rather than HEAD: some CDNs answer HEAD with a status that
    says nothing useful, and a kilobyte is enough to see the content type.
    """
    try:
        response = await client.get(url, headers={"Range": "bytes=0-1023"})
    except httpx.HTTPError:
        return False
    return response.status_code in (200, 206) and response.headers.get(
        "content-type", ""
    ).startswith("image/")


async def openverse_images(
    client: httpx.AsyncClient, query: str, *, limit: int = 3
) -> list[ImageCandidate]:
    """Openly-licensed images from across Flickr, museums and Wikimedia.

    This is the answer to Curio not being a Wikipedia reader. Openverse only
    indexes work under a licence that permits reuse, and returns the licence
    and a ready-made attribution string with every result, so the credit line
    a card has to print comes from the source rather than being assembled here.
    """
    try:
        response = await client.get(
            _OPENVERSE,
            params={
                "q": query,
                "page_size": limit * 3,
                # Public-domain and attribution licences only. Deliberately no
                # NC or ND: a card is a work of its own and may be read
                # anywhere, and a licence that forbids that is not worth the
                # argument over whether Curio counts as commercial.
                "license": "cc0,pdm,by,by-sa",
                "category": "illustration,photograph",
                "mature": "false",
            },
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        logger.debug("openverse search failed for %r: %s", query, exc)
        return []

    if response.status_code != 200:
        logger.debug("openverse returned %d for %r", response.status_code, query)
        return []

    try:
        results = response.json().get("results", [])
    except ValueError:
        return []

    out: list[ImageCandidate] = []
    for item in results:
        if len(out) >= limit:
            break
        if not _mentions_topic(item, query):
            continue
        # Wikimedia is already covered, and better, by the two collectors above:
        # they rasterise an SVG to PNG, where Openverse's thumbnail proxy simply
        # fails on the same file. Skipping them here is deduplication that
        # happens to remove the one case that was reliably broken.
        if str(item.get("source") or "") == "wikimedia":
            continue

        licence = str(item.get("license") or "").upper()
        version = str(item.get("license_version") or "")
        # "by-sa" + "4.0" -> "CC BY-SA 4.0"; "pdm" stays as it is.
        label = (
            f"CC {licence} {version}".strip()
            if licence not in {"CC0", "PDM"}
            else ("Public domain" if licence == "PDM" else "CC0")
        )

        candidate = ImageCandidate(
            url=_openverse_source(item),
            provider="openverse",
            source_url=str(item.get("foreign_landing_url") or ""),
            title=str(item.get("title") or "")[:200],
            credit=str(item.get("creator") or "")[:200],
            license=label[:80],
            license_url=str(item.get("license_url") or "")[:300],
            width=int(item.get("width") or 0),
            height=int(item.get("height") or 0),
        )
        if not usable(candidate) or _JUNK_TITLE.search(candidate.title):
            continue
        if not await _renders(client, candidate.url):
            logger.debug("openverse thumbnail does not render: %s", candidate.url)
            continue
        out.append(candidate)

    return out


# --- The registry -----------------------------------------------------------

PROVIDERS: dict[str, Any] = {
    "openverse": openverse_images,
    "wikipedia_body": wikipedia_article_images,
}
"""Topic searches, run for every card being synthesised.

Each entry is `async (client, query, *, limit) -> list[ImageCandidate]`, which
is all a new source has to implement — a NASA or PubMed Central collector drops
in here without touching the pipeline. The lead-image and Reddit collectors are
deliberately *not* in this table: they are keyed on a specific article or post
rather than on a search term, so they are called where that thing is known.
"""

SEARCH_TIMEOUT = httpx.Timeout(15.0)
"""Shorter than evidence retrieval. A picture is a bonus, and a slow image
provider must not be able to hold up publishing a card."""


async def search(
    topics: list[str], *, per_provider: int = 2
) -> list[ImageCandidate]:
    """Look for pictures of a card's subject across every registered source.

    Searched by *topic* rather than by the question, for the same reason
    `evidence.gather` is: image libraries are indexed by what a thing is
    called, and "why do soap bubbles show rainbow colours?" matches nothing
    while "thin-film interference" matches the diagram.

    Every provider fails independently and silently. The worst outcome of this
    whole function returning nothing is a card without a picture, which is the
    normal state of most cards anyway.
    """
    primary = next((t.strip() for t in topics if t and t.strip()), "")
    if not primary:
        return []

    async with httpx.AsyncClient(
        timeout=SEARCH_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        tasks = [
            provider(client, primary, limit=per_provider)
            for provider in PROVIDERS.values()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    out: list[ImageCandidate] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.debug("image provider failed: %s", result)
            continue
        out.extend(result)
    return out


# --- Reddit -----------------------------------------------------------------


def reddit_post_image(data: dict[str, Any]) -> ImageCandidate | None:
    """The picture attached to a Reddit post, if it has exactly one.

    Only genuine image posts qualify. A link post's preview is a screenshot of
    somebody's article, a gallery has no single subject, and a self post's
    thumbnail is a placeholder string rather than a URL.
    """
    if data.get("over_18") or data.get("spoiler") or data.get("is_gallery"):
        return None
    if data.get("post_hint") != "image":
        return None

    width = height = 0
    url = ""

    # The direct upload is preferred: preview.redd.it URLs are signed, expire,
    # and carry query parameters that do not survive being stored and replayed.
    direct = str(data.get("url_overridden_by_dest") or data.get("url") or "")
    if "i.redd.it" in direct:
        url = direct

    previews = (data.get("preview") or {}).get("images") or []
    if previews:
        source = previews[0].get("source") or {}
        width = int(source.get("width") or 0)
        height = int(source.get("height") or 0)
        if not url and source.get("url"):
            # Reddit HTML-escapes the ampersands in its own JSON payload.
            url = str(source["url"]).replace("&amp;", "&")

    if not url:
        return None

    candidate = ImageCandidate(
        url=url,
        provider="reddit",
        source_url=str(data.get("permalink") and f"https://www.reddit.com{data['permalink']}" or ""),
        title=str(data.get("title") or "")[:200],
        credit=f"u/{data.get('author')}" if data.get("author") else "",
        license="Posted by the asker on Reddit",
        license_url=str(data.get("permalink") and f"https://www.reddit.com{data['permalink']}" or ""),
        width=width,
        height=height,
        origin="question",
    )
    # The junk-title filter is wrong for Reddit — the title here is the question
    # itself, and "Why does this logo look wrong?" is a fine question — so only
    # the URL and dimension checks apply.
    candidate_title, candidate.title = candidate.title, ""
    ok = usable(candidate)
    candidate.title = candidate_title
    return candidate if ok else None
