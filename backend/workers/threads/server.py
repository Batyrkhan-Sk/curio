"""A rendering worker for Threads, and nothing more.

Threads serves a JavaScript shell to any plain HTTP client: the profile and tag
pages come back as ~256KB of bundle with no post text in them, identical byte
count whichever profile is asked for. The posts arrive later, from a client-side
fetch, which means reading them needs a browser rather than a parser.

That is the entire reason this service exists, and the reason it is separate.
Chromium is 400MB and can hang; the API image stays httpx-only and unaffected,
and a browser that wedges takes down a worker rather than the site.

The split of responsibility is deliberate: this returns *posts*, not questions.
Deciding what counts as a question worth a card lives in
`app/ingestion/sources/threads.py` with every other such decision, because that
judgement needs the filters, the translation cache and the rest of the pipeline
around it. All this knows is how to make Threads render and where the text sits
once it has.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from playwright.async_api import Browser, async_playwright
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("threads-worker")

SEARCH_URL = "https://www.threads.com/search?q={}&serp_type=tags"
PROFILE_URL = "https://www.threads.com/@{}"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

NAV_TIMEOUT_MS = int(os.getenv("THREADS_NAV_TIMEOUT_MS", "45000"))
SETTLE_MS = int(os.getenv("THREADS_SETTLE_MS", "2500"))
CONCURRENCY = int(os.getenv("THREADS_CONCURRENCY", "4"))
"""Tabs rendered at once. Each is real memory, so this and `mem_limit` in
docker-compose move together."""

SCROLLS = int(os.getenv("THREADS_SCROLLS", "6"))
"""Each scroll pulls in roughly another screen of posts. Six is where the
returns started flattening on a tag page in testing."""

_JSON_BLOCK = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)


class Post(BaseModel):
    text: str
    url: str = ""
    external_id: str = ""
    engagement: int = 0


class HarvestRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)
    profiles: list[str] = Field(default_factory=list)
    limit_per_tag: int = 40


class HarvestResponse(BaseModel):
    posts: list[Post]
    failures: dict[str, str] = Field(default_factory=dict)


def _walk(node: Any, key: str, out: list) -> None:
    """Collect every value stored under `key`, at any depth.

    The payload shape is Meta's private business and changes without notice, so
    nothing here depends on where `thread_items` sits — only that it exists
    somewhere inside.
    """
    if isinstance(node, dict):
        for found_key, value in node.items():
            if found_key == key:
                out.append(value)
            _walk(value, key, out)
    elif isinstance(node, list):
        for value in node:
            _walk(value, key, out)


def _posts_from_html(html: str) -> list[Post]:
    groups: list = []
    for block in _JSON_BLOCK.findall(html):
        if "thread_items" not in block:
            continue
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        _walk(payload, "thread_items", groups)

    posts: list[Post] = []
    seen: set[str] = set()

    for group in groups:
        items = group if isinstance(group, list) else [group]
        for item in items:
            if not isinstance(item, dict):
                continue
            post = item.get("post") if isinstance(item.get("post"), dict) else item
            caption = post.get("caption")
            text = ""
            if isinstance(caption, dict):
                text = caption.get("text") or ""
            if not text:
                text = post.get("text") or ""
            text = " ".join(str(text).split())
            if len(text) < 10 or text in seen:
                continue
            seen.add(text)

            code = post.get("code") or ""
            user = post.get("user") if isinstance(post.get("user"), dict) else {}
            username = user.get("username") or ""
            url = (
                f"https://www.threads.com/@{username}/post/{code}"
                if code and username
                else ""
            )
            likes = post.get("like_count")
            posts.append(
                Post(
                    text=text,
                    url=url,
                    external_id=f"threads:{code}" if code else "",
                    engagement=int(likes) if isinstance(likes, int) else 0,
                )
            )
    return posts


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_playwright() as playwright:
        app.state.browser = await playwright.chromium.launch(args=["--no-sandbox"])
        logger.info("chromium launched")
        try:
            yield
        finally:
            await app.state.browser.close()


app = FastAPI(title="Curio Threads worker", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    browser: Browser = app.state.browser
    return {"ok": browser.is_connected()}


async def _render(browser: Browser, url: str) -> str:
    context = await browser.new_context(user_agent=USER_AGENT, locale="en-US")
    try:
        page = await context.new_page()
        # Not "networkidle": Threads keeps connections open for its feed, so
        # idle may never arrive and the navigation times out on a page that
        # rendered perfectly well — measured, #didyouknow failed this way while
        # its neighbours succeeded. Wait for the DOM, then let the feed settle.
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        await page.wait_for_timeout(SETTLE_MS)
        # Threads paginates on scroll; without this only the first screen of
        # posts is ever in the DOM.
        for _ in range(SCROLLS):
            await page.mouse.wheel(0, 4000)
            await page.wait_for_timeout(1500)
        return await page.content()
    finally:
        await context.close()


@app.post("/harvest", response_model=HarvestResponse)
async def harvest(request: HarvestRequest) -> HarvestResponse:
    """Render each tag and profile, and return the posts found.

    One target failing is normal — a tag with no posts, a profile behind a
    login wall — and must not fail the batch, so failures are reported
    alongside whatever did work rather than raised.
    """
    browser: Browser = app.state.browser
    collected: list[Post] = []
    failures: dict[str, str] = {}
    seen: set[str] = set()

    targets = [(f"#{tag}", SEARCH_URL.format(tag)) for tag in request.tags]
    targets += [(f"@{name}", PROFILE_URL.format(name)) for name in request.profiles]

    # Rendering serially costs ~15s a target, which put a 22-tag request past
    # the caller's timeout while this kept working on a request nobody was
    # waiting for any more. Bounded rather than unbounded: each context is a
    # browser tab, and enough of them at once will exhaust the memory limit.
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def one(label: str, url: str) -> tuple[str, list[Post] | str]:
        async with semaphore:
            try:
                html = await _render(browser, url)
            except Exception as exc:  # noqa: BLE001 — a dead target is data
                logger.warning("%s failed: %s", label, exc)
                return label, str(exc)[:200] or exc.__class__.__name__
            found = _posts_from_html(html)
            logger.info("%s: %d posts", label, len(found))
            return label, found

    for label, result in await asyncio.gather(*(one(l, u) for l, u in targets)):
        if isinstance(result, str):
            failures[label] = result
            continue
        for post in result[: request.limit_per_tag]:
            if post.text in seen:
                continue
            seen.add(post.text)
            collected.append(post)

    return HarvestResponse(posts=collected, failures=failures)
