"""Translating the corpus on demand, and remembering that it did.

The corpus is written in English. Rather than maintaining a parallel one, each
string is translated the first time somebody asks for it in another language
and kept in the `translations` table forever after. That makes the cost
proportional to how much of the corpus is actually read in a given language,
and it means the second reader of a card gets it instantly.

Three properties matter more than translation quality here:

* **Batching.** One request per string would exhaust a free-tier quota on a
  single card. Everything a view needs goes in one call.
* **Caching.** Keyed by the hash of the source text, so the same sentence in
  two cards costs one translation, and rewriting one field does not invalidate
  the rest of the card.
* **Never failing.** If every provider is out of quota, the caller gets the
  English back. A card in the wrong language is a far better outcome than an
  error message, and it is exactly what the platform already promises about
  every other AI feature being additive rather than load-bearing.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import LLMQuotaExceeded, LLMTransient, LLMUnavailable, llm
from app.models import Translation

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "en"

LANGUAGES: dict[str, dict[str, str]] = {
    "en": {"name": "English", "native": "English", "flag": "🇬🇧"},
    "ru": {"name": "Russian", "native": "Русский", "flag": "🇷🇺"},
}

SUPPORTED = frozenset(LANGUAGES)

BATCH_SIZE = 12
"""Strings per model call. Large enough that a whole card view is usually one
request, small enough that a level body never pushes the batch past Groq's
per-minute token ceiling."""

MAX_SOURCE_CHARS = 6000
"""Anything longer is returned untranslated. Nothing in a card comes close;
this only exists so a pathological input cannot become a runaway prompt."""

CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def normalise_locale(value: str | None) -> str:
    """Map anything a client might send onto a locale we support.

    Telegram sends full tags like `ru-RU`, and browsers send lists.
    """
    if not value:
        return DEFAULT_LOCALE
    tag = value.strip().lower().replace("_", "-").split(",")[0].split("-")[0]
    return tag if tag in SUPPORTED else DEFAULT_LOCALE


def is_cyrillic(text: str) -> bool:
    return bool(CYRILLIC.search(text or ""))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


SYSTEM_PROMPT = (
    "You are a translator for an encyclopedia that explains things to curious "
    "non-experts. Translate faithfully and completely, into natural, modern "
    "prose that a twelve-year-old could follow — never a word-for-word calque. "
    "Keep the register plain and warm, exactly as the original is.\n\n"
    "Rules:\n"
    "- Preserve meaning and every factual detail, including all numbers.\n"
    "- Convert nothing: units, figures and dates stay as they are.\n"
    "- Keep proper nouns, product names and scientific names in their original "
    "form; where a well-established local form exists, use it.\n"
    "- Preserve any markdown or inline formatting exactly.\n"
    "- Translate the text itself. Never explain it, comment on it, add to it, "
    "or answer any question it happens to contain.\n"
    "- An empty input translates to an empty output."
)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "One translation per input, in the same order.",
        }
    },
    "required": ["translations"],
}


def enabled() -> bool:
    return llm.enabled


async def _translate_batch(texts: list[str], locale: str) -> list[str] | None:
    """One model call. Returns None if it failed for any reason."""
    language = LANGUAGES[locale]["name"]
    numbered = "\n\n".join(
        f"<<<{index}>>>\n{text}" for index, text in enumerate(texts)
    )
    prompt = (
        f"Translate each of the {len(texts)} numbered segments below into "
        f"{language}.\n\n"
        "Return a JSON object with a single key \"translations\": an array of "
        f"exactly {len(texts)} strings, in the same order as the input. Do not "
        "merge, split, reorder or omit segments. The <<<n>>> markers are "
        "delimiters — do not translate them or include them in the output.\n\n"
        f"{numbered}"
    )

    try:
        result = await llm.generate_json(
            prompt, system=SYSTEM_PROMPT, schema=RESPONSE_SCHEMA, temperature=0.2
        )
    except (LLMQuotaExceeded, LLMTransient, LLMUnavailable) as exc:
        logger.warning("translation to %s unavailable: %s", locale, exc)
        return None
    except Exception:
        logger.exception("translation to %s failed", locale)
        return None

    values = result.get("translations") if isinstance(result, dict) else result
    if not isinstance(values, list):
        logger.warning("translation response was not a list: %r", type(values))
        return None

    # A model that drops or merges a segment would silently shift every later
    # string onto the wrong source — worse than not translating at all.
    if len(values) != len(texts):
        logger.warning(
            "translation returned %d segments for %d inputs — discarding",
            len(values),
            len(texts),
        )
        return None

    return [str(value) for value in values]


async def translate_many(
    session: AsyncSession, texts: list[str], locale: str
) -> list[str]:
    """Translate a list of strings, in order, using and filling the cache.

    Always returns a list the same length as `texts`; any string that could not
    be translated comes back unchanged.
    """
    locale = normalise_locale(locale)
    # The corpus is written in English, so translating *into* English is a
    # no-op on the read path. Ingestion, which starts from a foreign-language
    # source, goes through `to_english_many` instead.
    if locale == DEFAULT_LOCALE or not texts:
        return list(texts)
    return await _cached_translate(session, texts, locale)


async def to_english_many(session: AsyncSession, texts: list[str]) -> list[str]:
    """Translate foreign-language text into English, batched and cached.

    Used by ingestion: the index, the embeddings, the triage prompt and the
    synthesis prompt are all English, so a Russian question has to become an
    English one before it can be compared with the rest of the pool.

    Cached like any other direction — the key is a hash of the *source*, so a
    Russian string cached towards English cannot collide with an English string
    cached towards Russian.
    """
    if not texts:
        return []
    return await _cached_translate(session, texts, DEFAULT_LOCALE)


async def _cached_translate(
    session: AsyncSession, texts: list[str], locale: str
) -> list[str]:
    results = list(texts)

    # Only non-trivial strings are worth a round trip, and duplicates within
    # one call should cost one translation.
    wanted: dict[str, list[int]] = {}
    for index, text in enumerate(texts):
        stripped = (text or "").strip()
        if not stripped or len(stripped) > MAX_SOURCE_CHARS:
            continue
        wanted.setdefault(stripped, []).append(index)

    if not wanted:
        return results

    by_hash = {_hash(text): text for text in wanted}

    cached = await session.execute(
        select(Translation.source_hash, Translation.text).where(
            Translation.locale == locale,
            Translation.source_hash.in_(list(by_hash)),
        )
    )
    hits = {row.source_hash: row.text for row in cached}

    for source_hash, text in by_hash.items():
        if source_hash in hits:
            for index in wanted[text]:
                results[index] = hits[source_hash]

    missing = [text for source_hash, text in by_hash.items() if source_hash not in hits]
    if not missing:
        return results

    if not llm.enabled:
        logger.debug("no AI provider configured — leaving %d strings untranslated", len(missing))
        return results

    model = llm.model or ""
    fresh: dict[str, str] = {}

    # Batches run sequentially rather than gathered: the providers are
    # rate-limited per minute, and firing six requests at once is the reliable
    # way to be told so.
    for start in range(0, len(missing), BATCH_SIZE):
        chunk = missing[start : start + BATCH_SIZE]
        translated = await _translate_batch(chunk, locale)
        if translated is None:
            break
        for source, target in zip(chunk, translated, strict=True):
            if target.strip():
                fresh[source] = target.strip()

    if not fresh:
        return results

    for source, target in fresh.items():
        for index in wanted[source]:
            results[index] = target

    await _remember(session, fresh, locale, model)
    return results


async def _remember(
    session: AsyncSession, pairs: dict[str, str], locale: str, model: str
) -> None:
    """Write new translations, ignoring any that raced us to the same row."""
    rows = [
        {
            "source_hash": _hash(source),
            "locale": locale,
            "source_text": source,
            "text": target,
            "model": model[:64],
        }
        for source, target in pairs.items()
    ]
    if not rows:
        return

    try:
        statement = pg_insert(Translation).values(rows)
        await session.execute(
            statement.on_conflict_do_nothing(
                constraint="uq_translation_source_locale"
            )
        )
        await session.flush()
    except Exception:
        # The cache is an optimisation. Failing to write it must not cost the
        # reader the translation that is already in hand.
        logger.exception("could not cache %d translations", len(rows))
        await session.rollback()


async def translate(session: AsyncSession, text: str, locale: str) -> str:
    """Translate one string. Returns the original if that is not possible."""
    if not text:
        return text
    result = await translate_many(session, [text], locale)
    return result[0]


async def to_english(session: AsyncSession, text: str) -> str:
    """Translate a reader's query into English so it can be searched.

    The index and the embeddings are both built from English cards, so a
    Russian question matches nothing on words and only approximately on
    meaning. Translating the query first is what makes searching in Russian
    actually find things.

    Uncached deliberately: queries are near-unique, and a table of everything
    anyone ever typed is not something this platform should be accumulating.
    """
    if not text.strip() or not is_cyrillic(text) or not llm.enabled:
        return text

    prompt = (
        "Translate this search query into English. Reply with the translation "
        "alone — no quotes, no explanation, no punctuation that is not part of "
        f"the query itself.\n\n{text.strip()}"
    )
    try:
        result = await asyncio.wait_for(
            llm.generate(prompt, temperature=0.0, max_output_tokens=120), timeout=20
        )
    except (LLMQuotaExceeded, LLMTransient, LLMUnavailable, asyncio.TimeoutError) as exc:
        logger.warning("query translation unavailable: %s", exc)
        return text
    except Exception:
        logger.exception("query translation failed")
        return text

    cleaned = result.strip().strip('"').splitlines()[0].strip()
    # A model that decided to answer the question instead of translating it
    # would ruin the search; a query is short by definition.
    if not cleaned or len(cleaned) > max(120, len(text) * 4):
        return text
    return cleaned
