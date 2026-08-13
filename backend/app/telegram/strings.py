"""Everything the bot says in its own voice.

Card content is translated by a model at read time; this is not. The bot's
chrome is a fixed, small vocabulary that appears on every screen, and running
it through an LLM would mean paying for it, waiting for it, and letting the
same button be worded two different ways on two different days.

Keys missing from a locale fall back to English rather than showing a key,
so a half-finished translation degrades into a mixed interface instead of a
broken one.
"""

from __future__ import annotations

from typing import Any

from app.services.translation import DEFAULT_LOCALE, LANGUAGES, normalise_locale

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # --- card chrome ---
        "minutes": "{n} min",
        "confidence": "{n}% confidence",
        "level_position": "level {index} of {total}",
        "trimmed": "Trimmed to fit a message — the full level is in the app.",
        "key_terms": "Key terms",
        "no_terms": "This card introduces no new terms.",
        "myths": "Commonly believed, but wrong",
        "no_myths": "No widespread misconception is recorded for this one.",
        "sources": "What this is built on",
        "no_sources": "No sources are recorded for this card.",
        "difficulty_beginner": "beginner",
        "difficulty_intermediate": "intermediate",
        "difficulty_advanced": "advanced",
        "difficulty_expert": "expert",
        # --- search ---
        "nothing_found": "Nothing found for <b>{query}</b>.",
        "search_hint": "Try fewer words — the search matches meaning as well as spelling.",
        "saved_heading": "Saved",
        "query_too_short": "Give me a little more to go on — a few words at least.",
        # Plain text: the renderer escapes it and supplies the emphasis, so a
        # tag here would arrive on screen as literal &lt;i&gt;.
        "searching_translated": "Searched for “{query}”",
        # --- buttons ---
        "btn_save": "🔖 Save",
        "btn_saved": "🔖 Saved",
        "btn_overview": "↩ Overview",
        "btn_another": "🔀 Another",
        "btn_open": "📖 Open in Curio",
        "btn_open_app": "📖 Open Curio",
        "btn_search_app": "🔎 Search in Curio",
        "btn_surprise": "🔀 Surprise me",
        "btn_read_inline": "📖 Read on Curio",
        "btn_language": "🌐 Language",
        "btn_mode": "🎚 What to show",
        "btn_start_reading": "🌱 {label}",
        # --- modes ---
        "mode_interesting": "✦ Interesting",
        "mode_useful": "⚑ Useful in life",
        "mode_prompt": (
            "<b>What should I show you?</b>\n\n"
            "<b>✦ Interesting</b> — the questions that are a pleasure to know "
            "the answer to. The sky, black holes, why onions make you cry.\n\n"
            "<b>⚑ Useful in life</b> — the answers that change what you do: "
            "safety, scams and passwords, money, keeping things working. "
            "The ones worth knowing <i>before</i> you need them.\n\n"
            "This sets what /random draws from, and how the app opens."
        ),
        "mode_set_interesting": "Showing what's interesting. /random will surprise you.",
        "mode_set_useful": (
            "Showing what's useful. /random now draws from the answers that "
            "are worth having in advance."
        ),
        "mode_empty_useful": (
            "Nothing practical in the library yet — showing everything instead."
        ),
        # --- replies ---
        "text_only": "I only read text — send me a question and I will find the card for it.",
        "unknown_command": "I don't know that one.",
        "empty_library": "The library is empty — nothing to show yet.",
        "nothing_saved": (
            "Nothing saved yet. Tap <b>🔖 Save</b> on any card and it lands here — "
            "and on the Saved page in the app."
        ),
        "card_gone": "That card is gone.",
        "toast_saved": "Saved — it's on your Saved page.",
        "toast_removed": "Removed.",
        # --- stats ---
        "stats_heading": "What you have read",
        "stats_read": "Cards read",
        "stats_saved": "Saved",
        "stats_completed": "Finished",
        "stats_concepts": "Concepts met",
        "stats_time": "Time spent",
        "stats_streak": "Streak",
        "stats_days": "{n} days",
        "stats_best": "best {n}",
        "stats_minutes": "{n} min",
        # --- language ---
        "language_prompt": (
            "<b>Reading language</b>\n\n"
            "Cards are written in English and translated on request. "
            "The translation is kept, so a card you have opened before appears "
            "instantly next time."
        ),
        "language_set": "Reading in English from now on.",
        "language_unavailable": (
            "⚠️ No AI provider is reachable right now, so cards will stay in "
            "English until one is. Everything else works."
        ),
        # --- welcome / help ---
        "welcome": (
            "{greeting} — this is <b>Curio</b>.\n\n"
            "It indexes the questions people keep asking rather than the pages "
            "that answer them badly. Every card starts at an explanation a "
            "twelve-year-old could follow and goes five levels down to expert "
            "detail.\n\n"
            "<b>Try:</b>\n"
            "• Send me anything you are curious about\n"
            "• /random — something unexpected\n"
            "• /mode — interesting, or useful in life\n"
            "• /saved — what you kept\n"
            "• /lang — read in Russian\n"
            "• Type <code>@{bot} wifi</code> in any chat to share a card\n\n"
            "<i>Tap Read Curio beside the message box for the full reader.</i>"
        ),
        "welcome_greeting": "Hello {name}",
        "welcome_greeting_anon": "Hello",
        "help": (
            "<b>What I can do</b>\n\n"
            "<b>/random</b> — a card picked for no reason at all\n"
            "<b>/mode</b> — choose between interesting and useful in life\n"
            "<b>/search</b> &lt;question&gt; — or just send the question on its own\n"
            "<b>/saved</b> — the cards you kept\n"
            "<b>/stats</b> — what you have read\n"
            "<b>/lang</b> — switch between English and Russian\n\n"
            "In any other chat, type <code>{mention} something</code> to search "
            "without leaving the conversation.\n\n"
            "Inside a card: <b>◀ ▶</b> move between the five levels, "
            "<b>🧠</b> lists the terms it introduces, <b>⚠️</b> the "
            "misconceptions, and <b>📚</b> the sources it was built from."
        ),
    },
    "ru": {
        # --- card chrome ---
        "minutes": "{n} мин",
        "confidence": "уверенность {n}%",
        "level_position": "уровень {index} из {total}",
        "trimmed": "Сокращено до размера сообщения — целиком уровень есть в приложении.",
        "key_terms": "Ключевые понятия",
        "no_terms": "Эта карточка не вводит новых понятий.",
        "myths": "Распространённое заблуждение",
        "no_myths": "Для этого вопроса известных заблуждений не записано.",
        "sources": "На чём это основано",
        "no_sources": "Источники для этой карточки не указаны.",
        "difficulty_beginner": "для начинающих",
        "difficulty_intermediate": "средний уровень",
        "difficulty_advanced": "продвинутый уровень",
        "difficulty_expert": "экспертный уровень",
        # --- search ---
        "nothing_found": "По запросу <b>{query}</b> ничего не нашлось.",
        "search_hint": "Попробуйте короче — поиск понимает и смысл, и написание.",
        "saved_heading": "Сохранённое",
        "query_too_short": "Слишком коротко — напишите хотя бы несколько слов.",
        "searching_translated": "Искали «{query}»",
        # --- buttons ---
        "btn_save": "🔖 Сохранить",
        "btn_saved": "🔖 Сохранено",
        "btn_overview": "↩ К началу",
        "btn_another": "🔀 Ещё",
        "btn_open": "📖 Открыть в Curio",
        "btn_open_app": "📖 Открыть Curio",
        "btn_search_app": "🔎 Искать в Curio",
        "btn_surprise": "🔀 Удивите меня",
        "btn_read_inline": "📖 Читать в Curio",
        "btn_language": "🌐 Язык",
        "btn_mode": "🎚 Что показывать",
        "btn_start_reading": "🌱 {label}",
        # --- modes ---
        "mode_interesting": "✦ Интересное",
        "mode_useful": "⚑ Полезное в жизни",
        "mode_prompt": (
            "<b>Что вам показывать?</b>\n\n"
            "<b>✦ Интересное</b> — вопросы, ответ на которые приятно знать. "
            "Небо, чёрные дыры, почему от лука плачут.\n\n"
            "<b>⚑ Полезное в жизни</b> — ответы, которые меняют поведение: "
            "безопасность, мошенники и пароли, деньги, уход за вещами. "
            "Те, что стоит знать <i>заранее</i>.\n\n"
            "Отсюда /random берёт карточки, и с этим же открывается приложение."
        ),
        "mode_set_interesting": "Показываю интересное. /random будет удивлять.",
        "mode_set_useful": (
            "Показываю полезное. Теперь /random берёт из ответов, которые "
            "лучше знать заранее."
        ),
        "mode_empty_useful": (
            "Практических карточек в библиотеке пока нет — показываю всё подряд."
        ),
        # --- replies ---
        "text_only": "Я читаю только текст — напишите вопрос, и я найду карточку.",
        "unknown_command": "Такой команды я не знаю.",
        "empty_library": "Библиотека пуста — показывать пока нечего.",
        "nothing_saved": (
            "Пока ничего не сохранено. Нажмите <b>🔖 Сохранить</b> на любой карточке — "
            "она появится здесь и на странице «Сохранённое» в приложении."
        ),
        "card_gone": "Этой карточки больше нет.",
        "toast_saved": "Сохранено — карточка на странице «Сохранённое».",
        "toast_removed": "Убрано.",
        # --- stats ---
        "stats_heading": "Что вы прочитали",
        "stats_read": "Прочитано карточек",
        "stats_saved": "Сохранено",
        "stats_completed": "Пройдено до конца",
        "stats_concepts": "Встречено понятий",
        "stats_time": "Потрачено времени",
        "stats_streak": "Серия дней",
        "stats_days": "{n} дн.",
        "stats_best": "рекорд {n}",
        "stats_minutes": "{n} мин",
        # --- language ---
        "language_prompt": (
            "<b>Язык чтения</b>\n\n"
            "Карточки написаны по-английски и переводятся по запросу. "
            "Перевод сохраняется, поэтому уже открытая карточка появляется "
            "мгновенно."
        ),
        "language_set": "Дальше читаем по-русски.",
        "language_unavailable": (
            "⚠️ Сейчас ни один ИИ-провайдер недоступен, поэтому карточки "
            "останутся на английском, пока связь не вернётся. Всё остальное работает."
        ),
        # --- welcome / help ---
        "welcome": (
            "{greeting} — это <b>Curio</b>.\n\n"
            "Здесь собраны вопросы, которые люди задают снова и снова, а не "
            "страницы, которые плохо на них отвечают. Каждая карточка начинается "
            "с объяснения, понятного двенадцатилетнему, и уходит на пять уровней "
            "вглубь — до экспертных подробностей.\n\n"
            "<b>Попробуйте:</b>\n"
            "• Напишите всё, что вам любопытно\n"
            "• /random — что-нибудь неожиданное\n"
            "• /mode — интересное или полезное в жизни\n"
            "• /saved — то, что вы сохранили\n"
            "• /lang — сменить язык\n"
            "• Наберите <code>@{bot} wifi</code> в любом чате, чтобы поделиться карточкой\n\n"
            "<i>Кнопка рядом с полем ввода открывает полноценную читалку.</i>"
        ),
        "welcome_greeting": "Здравствуйте, {name}",
        "welcome_greeting_anon": "Здравствуйте",
        "help": (
            "<b>Что я умею</b>\n\n"
            "<b>/random</b> — карточка совершенно без повода\n"
            "<b>/mode</b> — выбрать между интересным и полезным в жизни\n"
            "<b>/search</b> &lt;вопрос&gt; — или просто пришлите сам вопрос\n"
            "<b>/saved</b> — сохранённые карточки\n"
            "<b>/stats</b> — что вы прочитали\n"
            "<b>/lang</b> — переключить русский и английский\n\n"
            "В любом другом чате наберите <code>{mention} что-нибудь</code>, "
            "чтобы искать не выходя из разговора.\n\n"
            "Внутри карточки: <b>◀ ▶</b> — переход между пятью уровнями, "
            "<b>🧠</b> — понятия, которые она вводит, <b>⚠️</b> — заблуждения, "
            "<b>📚</b> — источники."
        ),
    },
}


def t(locale: str, key: str, **values: Any) -> str:
    """Look up a string, falling back to English for anything untranslated."""
    locale = normalise_locale(locale)
    template = STRINGS.get(locale, {}).get(key) or STRINGS[DEFAULT_LOCALE].get(key, key)
    if not values:
        return template
    try:
        return template.format(**values)
    except (KeyError, IndexError):
        # A placeholder mismatch in one translation should not take the message
        # down with it.
        return STRINGS[DEFAULT_LOCALE].get(key, key).format(**values)


def language_label(locale: str) -> str:
    meta = LANGUAGES.get(locale)
    if not meta:
        return locale
    return f"{meta['flag']} {meta['native']}"


def difficulty_label(locale: str, difficulty: str) -> str:
    return t(locale, f"difficulty_{difficulty}") if difficulty else ""
