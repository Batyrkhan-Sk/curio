"""Shared types for question discovery sources."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

QUESTION_RE = re.compile(
    r"^\s*(why|how|what|when|where|which|does|do|is|are|can|could|would|should)\b",
    re.IGNORECASE,
)

_NOISE = re.compile(
    r"\b(help|urgent|please|asap|my (laptop|pc|code|app|build)|not working|error|"
    r"how do i (fix|install|uninstall)|anyone know|solved|\[closed\]|hiring|job)\b",
    re.IGNORECASE,
)

# Russian-language filtering, for sources like Habr Q&A.
#
# The polarity is deliberately reversed here. For English forums the rule is
# "anything question-shaped, minus obvious noise", because those sources are
# curated communities that already ask durable questions. A Russian IT Q&A site
# is not that: it is overwhelmingly people whose build is broken tonight. Left
# on the permissive setting it passes everything — measured, 21 of 21 on a live
# page — and hands the whole support queue to the triage model to pay for.
#
# So Russian text has to look *positively* like a question about how something
# works, and must not carry any of the marks of a support request.
RU_QUESTION_RE = re.compile(
    r"^\s*(почему|отчего|зачем|"
    r"как\s+(работает|работают|устроен\w*|происходит|получается|связан\w*)|"
    r"что\s+такое|что\s+происходит|"
    r"в\s+ч[ёе]м\s+(разница|отличие|смысл|причина)|"
    r"чем\s+отлича\w+|"
    r"правда\s+ли|верно\s+ли|"
    r"откуда\s+бер[ёе]тся|откуда\s+бер[ýу]тся|"
    r"существует\s+ли|бывает\s+ли|может\s+ли)\b",
    re.IGNORECASE,
)
"""What a durable question opens with. Anything else in Cyrillic is dropped."""

_RU_NOISE_PARTS = (
    # Something is broken right now.
    r"не\s+работает",
    r"не\s+запускается",
    r"не\s+включается",
    r"не\s+открывается",
    r"не\s+подключается",
    r"не\s+отображается",
    r"не\s+видит",
    r"не\s+грузит",
    r"не\s+могу",
    r"не\s+получается",
    r"не\s+находит",
    r"зависает",
    r"вылетает",
    r"тормозит",
    r"глючит",
    r"ошибк\w*",
    r"баг\b",
    # Asking for help rather than for an explanation.
    r"помогите",
    r"подскажите",
    r"посоветуйте",
    r"нужен\s+совет",
    r"что\s+делать",
    r"что\s+не\s+так",
    r"куда\s+копать",
    r"срочно",
    # Task assistance: how do I make my specific thing do this.
    r"как\s+(сделать|реализовать|исправить|починить|настроить|установить|"
    r"удалить|обойти|добавить|заставить|организовать)",
    # Shopping, careers and course recommendations.
    r"стоит\s+ли\s+брать",
    r"что\s+выбрать",
    r"какой\s+выбрать",
    r"ищу\s+работу",
    r"вакансия",
    r"резюме",
    r"собеседовани",
    r"с\s+чего\s+начать",
    r"курс\w*\s+по\b",
    # A negated *reflexive* verb — "не переустанавливается", "не подключается",
    # "не отображается" — is almost always somebody's own thing failing to do
    # something. Active negations describe the world and are left alone, which
    # is the difference between "почему не переустанавливается винда" and
    # "почему сигнал не затухает".
    r"не\s+\w*(ется|ится)\b",
)

# Built by joining rather than by concatenating string literals: a stray `|` at
# the start of a continuation line silently creates an empty alternative, which
# matches every string and rejects the entire harvest. That bug is invisible on
# inspection and total in effect.
_RU_NOISE = re.compile("(" + "|".join(_RU_NOISE_PARTS) + ")", re.IGNORECASE)

_CYRILLIC = re.compile(r"[Ѐ-ӿ]")

_WHITESPACE = re.compile(r"\s+")
_TRAILING = re.compile(r"[\s\-–—:;,.]+$")


@dataclass(slots=True)
class DiscoveredQuestion:
    """One observation that somebody, somewhere, was curious about this."""

    raw_text: str
    source_name: str
    source_url: str = ""
    external_id: str = ""
    engagement: int = 0
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    original_text: str = ""
    """The question as it was actually asked, when that was not in English.
    `raw_text` carries the English form the pipeline works in; this is what the
    card cites, because claiming somebody asked a question in words they never
    used is a small lie the "where this came from" section should not tell."""

    original_language: str = ""

    @property
    def normalized_text(self) -> str:
        return normalize_question(self.raw_text)


def normalize_question(text: str) -> str:
    """Collapse a raw title into a comparable form.

    Used for cheap exact-duplicate detection before the expensive embedding
    comparison runs.
    """
    cleaned = _WHITESPACE.sub(" ", text.strip().lower())
    cleaned = re.sub(r"^\[[^\]]{1,20}\]\s*", "", cleaned)  # [Discussion] prefixes
    cleaned = re.sub(r"^(eli5|tifu|ask hn|ask reddit)[:\s-]+", "", cleaned)
    cleaned = _TRAILING.sub("", cleaned)
    return cleaned


def is_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC.search(text or ""))


def looks_like_durable_question(text: str) -> bool:
    """Cheap pre-filter before spending an LLM call on triage.

    Intentionally permissive — the model does the real judging. This only
    removes what is obviously not a question about how the world works.

    Russian text is judged by the Russian patterns. Translating first would be
    the wrong order: the point of this filter is to decide what is worth
    spending a model call on, so it has to run before any translation does.
    """
    stripped = text.strip()
    if len(stripped) < 15 or len(stripped) > 180:
        return False
    if stripped.count("?") > 2:
        return False

    if is_cyrillic(stripped):
        # Both conditions, not either: the opening has to promise an
        # explanation, and nothing in the rest may reveal a support request
        # wearing one. "Почему не включается ПК" opens correctly and is still
        # somebody's dead motherboard.
        if not RU_QUESTION_RE.match(stripped):
            return False
        return not _RU_NOISE.search(stripped)

    if not QUESTION_RE.match(stripped) and "?" not in stripped:
        return False
    return not _NOISE.search(stripped)


# --- Practical questions --------------------------------------------------
# A third profile, for the CIS/KZ everyday sources. The mechanism patterns
# above are the wrong instrument here and reject essentially everything these
# sources carry: "Можно ли вернуть товар без чека?" opens with none of the
# durable cues, and "как оформить" is explicitly *noise* to the mechanism
# filter because there it means "make my thing do this".
#
# For a practical source that phrasing is the signal, not the noise. What
# somebody needs to do to get a document, what a deadline is, who is liable —
# these have answers that are looked up rather than derived, and they are the
# questions people actually need answered. So the polarity flips again: an
# explicit allow-list of practical openings, searched anywhere in the line
# because a forum title puts the question after the throat-clearing
# ("Подскажите, можно ли…").
_RU_PRACTICAL_PARTS = (
    # Permission, obligation and entitlement — the bulk of it.
    r"можно\s+ли",
    r"нужно\s+ли",
    r"надо\s+ли",
    r"обязан\w*\s+ли",
    r"обязательно\s+ли",
    r"положено\s+ли",
    r"вправе\s+ли",
    r"имеет\s+ли\s+прав\w+",
    r"законно\s+ли",
    r"правомерн\w*\s+ли",
    r"считается\s+ли",
    r"облагается\s+ли",
    r"распространяется\s+ли",
    r"входит\s+ли",
    # What the rules are.
    r"каки\w+\s+документ\w+",
    r"как\w+\s+(штраф|ответственность|срок|размер|компенсация|пошлина)",
    r"каки\w+\s+прав\w+",
    r"сколько\s+(стоит|платить|составляет|дней|лет|раз|нужно)",
    r"в\s+какой\s+срок",
    # The administrative verbs. Noise to the mechanism filter, signal here.
    r"как\s+(оформить|получить|вернуть|подать|расторгнуть|зарегистрировать|"
    r"восстановить|обжаловать|рассчитать|начисляется|оплачивается|"
    r"взыскать|доказать|подтвердить)",
    r"где\s+(получить|оформить|подать|узнать)",
    r"кто\s+(платит|оплачивает|несет|должен|отвечает)",
    r"что\s+(будет|грозит|положено|делать)\s+если",
    r"когда\s+(можно|нужно|положено|наступает)",
    # Everyday life rather than paperwork. The Q&A sources carry far more of
    # this than the legal forum does, and it is the same kind of question:
    # answerable, consequential, and nothing to do with a mechanism.
    r"вредно\s+ли",
    r"опасно\s+ли",
    r"полезно\s+ли",
    r"безопасно\s+ли",
    r"как\s+правильно\s+\w+",
    r"как\s+(хранить|мыть|стирать|сушить|чистить|разморозить|отстирать)",
    r"чем\s+(можно|лучше|опасен|опасна|вреден|вредна|заменить)",
    r"сколько\s+(хранится|можно\s+хранить|варить|держать)",
    r"через\s+сколько",
    r"правда\s+ли\s+что",
)
RU_PRACTICAL_RE = re.compile("(" + "|".join(_RU_PRACTICAL_PARTS) + ")", re.IGNORECASE)

# Deliberately much shorter than `_RU_NOISE`. A practical source is *supposed*
# to be full of people asking what to do, so "подскажите" and "что делать" are
# no longer disqualifying — the allow-list above already carries the burden of
# proof. What stays banned is a broken device, a job ad, and an advert.
_RU_PRACTICAL_NOISE_PARTS = (
    r"не\s+работает",
    r"не\s+включается",
    r"не\s+запускается",
    r"зависает",
    r"вылетает",
    r"требуется\s+\w+",
    r"ищу\s+работу",
    r"вакансия",
    r"резюме",
    r"собеседовани",
    r"продам",
    r"куплю",
    r"сдам",
    r"аренда\s+от",
    r"услуги\s+\w+\s+недорого",
    r"скидк\w+",
    r"акция\b",
    r"срочно",
)
_RU_PRACTICAL_NOISE = re.compile("(" + "|".join(_RU_PRACTICAL_NOISE_PARTS) + ")", re.IGNORECASE)


def looks_like_practical_question(text: str) -> bool:
    """The filter for everyday CIS/KZ sources.

    Answers here are jurisdiction-bound and go stale when the rules change,
    which is why what passes gets marked rather than treated as durable. That
    decision belongs to the card, not to this function — the job here is only
    to tell a question from a classified ad.
    """
    stripped = text.strip()
    if len(stripped) < 15 or len(stripped) > 180:
        return False
    if not is_cyrillic(stripped):
        return False
    if not RU_PRACTICAL_RE.search(stripped):
        return False
    return not _RU_PRACTICAL_NOISE.search(stripped)


# A question word anywhere in the line, rather than at the start of it.
_RU_QUESTION_ANYWHERE = re.compile(
    r"(почему|отчего|зачем|как\s+\w+|что\s+так\w+|что\s+будет|"
    r"в\s+ч[ёе]м\s+\w+|чем\s+отлича\w+|правда\s+ли|можно\s+ли|нужно\s+ли|"
    r"стоит\s+ли|откуда|насколько)",
    re.IGNORECASE,
)


_HEADLINE_TAG = re.compile(r"^\s*(\[[^\]]{1,24}\]\s*)+")
_HEADLINE_COLUMN = re.compile(r"^(спросите\s+[\w-]+|ask\s+[\w-]+)\s*[:—-]\s*", re.IGNORECASE)


def question_from_headline(title: str) -> str:
    """Reduce an article headline to the question inside it.

    Publishers wrap the question in furniture: a `[Перевод]` tag, the name of
    the column it ran in, and a subtitle after the question mark — "Как
    изобрели письменность? Часть 4. Крит, галеры, два письма". None of that is
    the question, and all of it would end up in the card title.
    """
    cleaned = _HEADLINE_TAG.sub("", title).strip()
    cleaned = _HEADLINE_COLUMN.sub("", cleaned).strip()

    mark = cleaned.find("?")
    if mark != -1:
        cleaned = cleaned[: mark + 1]
    return cleaned.strip()


def looks_like_question_headline(text: str) -> bool:
    """The looser test, for editorial titles rather than a Q&A firehose.

    An article headline is written to be read, not to be answered: the question
    often arrives mid-line ("Привод ответил ACK. Что он на самом деле
    пообещал?") and opens with verbs the strict test excludes ("Как изобрели
    письменность?"). Requiring the durable opening at position zero rejects
    every one of them — measured, 0 of 80 on two live feeds.

    What replaces it is a different kind of evidence: somebody wrote an article
    to answer this, and enough people read it for the feed to carry it. So the
    bar is a genuine question mark plus a question word somewhere, minus the
    same support noise.
    """
    stripped = text.strip()
    if len(stripped) < 15 or len(stripped) > 180:
        return False
    if "?" not in stripped:
        return False

    if is_cyrillic(stripped):
        if not _RU_QUESTION_ANYWHERE.search(stripped):
            return False
        return not _RU_NOISE.search(stripped)

    return not _NOISE.search(stripped)
