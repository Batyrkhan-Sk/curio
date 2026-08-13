"""Deterministic triage — the part of stage 3 that needs no model.

The LLM triage in `ai/pipeline.py` judges whether a question is *interesting*.
That is a genuine judgement call and it needs a model. But a large share of
what the collectors return is not a durable question at all: it is a personal
essay, a product announcement, or an opinion piece that merely starts with the
word "why". Those can be rejected on structure alone.

Running this first means the model only ever spends tokens on plausible
candidates, and it means the queue reflects reality even with no key set.

This pass only ever *rejects*. Deciding that something deserves a card stays
with the model, because that is the judgement it is actually good at.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Question

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    reason: str
    skip_when_practical: bool = False
    """Whether this rule is suspended for questions from a practical source.

    Four of these rules exist to reject a question for being somebody's own
    situation, and a practical question is *always* somebody's own situation:
    "Do I need a travel certificate?", "How do I get a quota for an
    operation?". Applied unchanged they reject the entire Kazakh harvest —
    measured, 5 of 6 on the first live sample. What makes those questions
    worth a card is that the answer generalises even though the asking did
    not, which is a distinction these patterns cannot see and the source can.
    """


RULES: tuple[Rule, ...] = (
    Rule(
        "first_person",
        re.compile(r"\b(i|i'm|i've|my|me|we|we're|our|us)\b", re.IGNORECASE),
        "personal account, not a question about the world",
        skip_when_practical=True,
    ),
    Rule(
        "announcement",
        re.compile(
            r"\b(is (switching|moving|migrating|shutting|closing)|"
            r"(quit|left|joined|acquired|acquires|launches|launched|releases|released)|"
            r"will not be|no longer|is dead|has died|shutting down|"
            r"(suing|sued|lawsuit|banned|bans))\b",
            re.IGNORECASE,
        ),
        "news or announcement rather than a mechanism",
    ),
    Rule(
        "opinion",
        re.compile(
            r"\b(should ?(n't| not)?( i| we| you| be)|you should|"
            r"is it worth|better than|worst|best way to|never use|"
            r"favorite|favourite|overrated|underrated|do you (think|prefer)|"
            r"change my mind|unpopular opinion|considered harmful|is a scam)\b",
            re.IGNORECASE,
        ),
        "opinion rather than an explainable question",
        skip_when_practical=True,
    ),
    Rule(
        "support_request",
        re.compile(
            r"\b(how (do|can) i|help me|not working|won't (boot|start|compile|run)|"
            r"error|exception|stack ?trace|troubleshoot|fix my|my (code|build|setup|laptop))\b",
            re.IGNORECASE,
        ),
        "a support request, answerable only for one person",
        skip_when_practical=True,
    ),
    Rule(
        "survey",
        re.compile(
            r"\b(y'?all|you guys|(does|did|has|have|can|could|would|will) any(one|body)|"
            r"anyone here|who else|"
            r"what('s| is| are) your|your (favorite|favourite|go.to)|"
            r"(you|u|ur) ever|you've ever|am i the only|tell me your|"
            r"what (do|did) you|which do you|how much do you)\b",
            re.IGNORECASE,
        ),
        "a poll of other people's experience, not a question with one answer",
    ),
    Rule(
        "instructions",
        re.compile(
            r"^(how|what|where) to\b|\b(step.by.step|tutorial|walk ?through|"
            r"where (can|do) i (buy|get|find)|recommend(ations?|ed)?\b|"
            r"any good\b|worth (buying|the money)|which (one )?should i (buy|get))\b",
            re.IGNORECASE,
        ),
        "asks for instructions or a recommendation rather than an explanation",
        skip_when_practical=True,
    ),
    Rule(
        "context_dependent",
        re.compile(
            r"\b(this|these|those)\s+(one|thing|item|part|piece|setup|system|device|"
            r"design|object|contraption|photo|picture|image|video|board|handle)\b"
            r"|\b(pictured|attached|in the (photo|picture|image|video)|identify (this|these))\b"
            # A question that trails off on a bare demonstrative is pointing at
            # the post body: "how to measure this?". "…wouldn't know it?" is not,
            # so "it" is deliberately absent here.
            r"|\b(this|these)\s*\?\s*$",
            re.IGNORECASE,
        ),
        "depends on something the reader cannot see",
    ),
    Rule(
        "dated",
        re.compile(r"\b(19|20)\d{2}\b|\b(today|yesterday|this (week|month|year))\b", re.IGNORECASE),
        "tied to a specific moment, so it will not stay true",
        skip_when_practical=True,
    ),
    Rule(
        "meta_platform",
        re.compile(
            r"\b(ask hn|show hn|tell hn|hn|reddit|hacker ?news|stack ?overflow|"
            r"twitter|x\.com|github|discord|slack)\b",
            re.IGNORECASE,
        ),
        "about a specific online platform rather than a general question",
    ),
    Rule(
        "job_or_promo",
        re.compile(r"\b(hiring|we're looking for|yc [swf]\d{2}|launch hn|discount|free trial)\b", re.IGNORECASE),
        "promotional",
    ),
)

# --- Normalisation -------------------------------------------------------
# The shape test is anchored at the start of the string, so anything a source
# glues on in front of the real question hides it: "ELI5: why are jet engines
# so loud?" is the same question as "why are jet engines so loud?".

SOURCE_PREFIX = re.compile(
    r"^\s*(?:\[[^\]]{0,30}\]|\([^)]{0,30}\)|"
    r"eli5|tifu|ask\s+hn(?:/\w+|\s+mods)?|show\s+hn|tell\s+hn|launch\s+hn|"
    r"question|serious|discussion|simply\s+explained|explained|help|"
    # Social-media framings that push the real question off position 0.
    # "Ever wonder why some trains have engines in the middle?" is exactly the
    # question the platform exists to answer, and the bare shape test sees a
    # sentence starting with "ever".
    r"ever\s+wonder(?:ed)?|(?:has\s+)?anyone\s+(?:ever\s+)?wonder(?:ed)?|"
    r"genuine\s+question|honest\s+question|real\s+question)"
    r"\s*[:;,\-–—]?\s+",
    re.IGNORECASE,
)

# A short scene-setting clause in front of the cue: "In steam turbines, why …".
LEADING_CLAUSE = re.compile(
    r"^[^,?]{0,60},\s+(?=(?:wh\w+|how|do|does|did|is|are|can|could|would)\b)",
    re.IGNORECASE,
)

# An editorial headline in front of the question: "Unlocking the Blockchain:
# What exactly is a Block?". The colon separates a title somebody wrote to be
# read from the question it actually asks, and only the second half is the
# question. The lookahead is what makes this safe — without a question cue
# after the colon nothing is stripped, so a title that merely contains one
# ("Bitcoin: a history") is left alone.
LEADING_TITLE = re.compile(
    r"^[^?:]{3,60}:\s+(?=(?:wh\w+|how|do|does|did|is|are|can|could|would|must)\b)",
    re.IGNORECASE,
)


_TYPOGRAPHIC = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def clean(text: str) -> str:
    """Decode a source's escaping and typography, changing no words.

    Collectors hand over `&#39;` and `’` interchangeably. Every rule below is
    written with a plain apostrophe, so without this `won’t` and `y’all` walk
    straight past the pattern that exists to catch them.
    """
    return html.unescape(text).translate(_TYPOGRAPHIC).strip()


def depackage(text: str) -> str:
    """Remove the submission conventions a site wraps around a question.

    "Ask HN:" and "ELI5:" say where a question was posted, not what it is
    about, so they are dropped before *any* judgement — otherwise a fine
    question is rejected as being about Hacker News purely for its prefix.
    """
    stripped = clean(text).lstrip("\"'")
    # Emoji, bullets and decorative symbols sit in front of the question on
    # social sources — "🌡️🪐 How Hot or Cold Are the Planets?" — and the shape
    # test is anchored, so they hide the cue exactly as "ELI5:" does. `\w` is
    # Unicode-aware here, so Cyrillic and other letters are never stripped.
    stripped = re.sub(r"^[\W_]+", "", stripped)
    previous = None
    while previous != stripped:
        previous = stripped
        stripped = SOURCE_PREFIX.sub("", stripped).strip()
    return stripped


def normalize(text: str) -> str:
    """Depackage, then drop a scene-setting clause in front of the question.

    Only ever used for the shape test. The content rules stop at `depackage`,
    because the clause this removes is often the evidence they need: drop the
    opening of "My MIL sold her house, where should she put the money?" and
    what is left looks like a perfectly general question.
    """
    stripped = depackage(text)
    previous = None
    while previous != stripped:
        previous = stripped
        stripped = LEADING_CLAUSE.sub("", stripped).strip()
        stripped = LEADING_TITLE.sub("", stripped).strip()
    return stripped


# A question has to *look* like one asking about a mechanism, not just end in
# a question mark. This is the only positive requirement in the pass.
#
# It is deliberately generous. Anything that survives here still has to get
# past the model in `ai/pipeline.py`, which is the stage that actually judges
# whether a question is worth a card and which rewrites the wording. Rejecting
# here is final and silent, so the bar is "could a mechanism question be
# phrased this way", not "is this phrased well".
_ADVERB = (
    r"(?:\s+(?:exactly|really|actually|precisely|even|ever|specifically|"
    r"generally|physically|technically|on\s+earth|the\s+hell))?"
)
MECHANISM_SHAPE = re.compile(
    # An open question: any wh-word, or "how", optionally with an adverb after it.
    rf"^(?:wh(?:y|at|en|ere|ich|o)|how){_ADVERB}\b"
    # Or a yes/no question, which is just as often a mechanism question:
    # "Do birds sleep while flying?", "Can an atom have more than 8 electrons?"
    r"|^(?:do|does|did|is|are|was|were|can|could|would|will|should|must|may|"
    r"has|have|had|if)\b",
    re.IGNORECASE,
)

# Sources whose questions are judged by the practical profile. A question from
# one of these is expected to be somebody's own situation with an answer that
# generalises — what a deadline is, who is liable, what a person has to do.
PRACTICAL_SOURCES: frozenset[str] = frozenset({"zakon.kz", "otvet.mail.ru"})

# Words that are capitalised because of Title Case rather than because they
# name anything. Their presence is what separates a headline from a question
# genuinely about a named product.
_TITLE_CASE_FILLER = frozenset(
    "a an the of in on at to for from by with and or but is are was were do does "
    "did can could would will should has have had how why what when where which "
    "who it its this that as not so if than then".split()
)


def evaluate(text: str, *, practical: bool = False) -> str | None:
    """Return a rejection reason, or None if the question survives.

    `practical` relaxes the rules that reject a question for being personal or
    instructional. It is set from the source rather than guessed from the text,
    because "Do I need a travel certificate?" and "Do I need a new laptop?" are
    the same shape and only one of them has an answer worth publishing.
    """
    cleaned = depackage(text)

    # Content rules come first, and read the whole question: they know *why*
    # something is unsuitable, and a specific reason is worth more than the
    # generic shape one. Run the other way round and every rejection collapses
    # into "not phrased as a question", which is both wrong and unreadable.
    for rule in RULES:
        if practical and rule.skip_when_practical:
            continue
        if rule.pattern.search(cleaned):
            return rule.reason

    stripped = normalize(text)
    if not MECHANISM_SHAPE.match(stripped):
        return "not phrased as a question about how something works"

    # A question carrying several capitalised words is often about a specific
    # named product or person rather than a general mechanism. Title Case
    # headlines are not evidence of that, though — a source that capitalises
    # "How Does an FPGA Work?" capitalises the filler words too, so ignore any
    # word that is only capitalised because the whole line is.
    # Quoted spans are terms the question is *about* ("Affirm / Negative"), and
    # they are capitalised for that reason rather than because they name a product.
    unquoted = re.sub(r"\"([^\"]{1,60})\"", " ", stripped)
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", unquoted)
    if len(words) >= 4:
        candidates = words[1:]
        named = [w for w in candidates if w[0].isupper() and w.lower() not in _TITLE_CASE_FILLER]
        title_cased = sum(1 for w in candidates if w[0].isupper())
        looks_title_case = title_cased / len(candidates) > 0.6

        # A real named thing is usually more than one capitalised word in a
        # row — "Google Maps", "Gaza Strip". A ratio alone cannot tell those
        # from a Title Cased sentence, which is how "How Hot or Cold Are the
        # Planets?" came to be read as a product name.
        runs = re.findall(r"(?:[A-Z][A-Za-z'-]+\s+){1,}[A-Z][A-Za-z'-]+", unquoted)
        has_proper_phrase = any(
            sum(1 for w in run.split() if w.lower() not in _TITLE_CASE_FILLER) >= 2
            for run in runs
        )

        if not looks_title_case and len(named) / len(words) > 0.4 and has_proper_phrase:
            return "about a specific named product or person"

    return None


async def run(session: AsyncSession, *, limit: int = 5000) -> dict:
    """Reject the structurally unsuitable questions in the pending pool."""
    rows = await session.execute(
        select(Question).where(Question.processed.is_(False)).limit(limit)
    )
    questions = list(rows.scalars())

    rejected = 0
    reasons: dict[str, int] = {}

    for question in questions:
        reason = evaluate(
            question.raw_text,
            practical=question.source_name in PRACTICAL_SOURCES,
        )
        if reason is None:
            continue
        question.processed = True
        question.rejected_reason = reason[:200]
        rejected += 1
        reasons[reason] = reasons.get(reason, 0) + 1

    await session.commit()

    report = {
        "examined": len(questions),
        "rejected": rejected,
        "survived": len(questions) - rejected,
        "reasons": dict(sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)),
    }
    logger.info("heuristic triage: %s", report)
    return report
