"""What the bot does when something happens.

One entry point, `handle_update`, and a small dispatch beneath it. There is no
conversation state anywhere: every button carries the card id and the position
it means, so a reader can come back to a message from three days ago and the
arrows still work. That is also why levels are shown by *editing* the message
rather than sending a new one — the chat stays one card per message instead of
five, and the card reads as a thing being turned over rather than a feed.

Language is the reader's, not the message's. Every view is localized at the
moment it is rendered, so switching to Russian and pressing ▶ continues the
same card in Russian.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import Card, Profile, TelegramLink
from app.services import discovery, personalization, search as search_service
from app.services import telegram, translation
from app.telegram import keyboards, localize, render
from app.telegram.initdata import TelegramUser, parse_user
from app.telegram.strings import t

logger = logging.getLogger(__name__)

SEARCH_RESULTS = 5
MIN_QUERY_LENGTH = 2


# --- Reader identity --------------------------------------------------------


async def link_for(
    session: AsyncSession,
    user: TelegramUser,
    *,
    chat_id: int | None = None,
    adopt_profile_key: str | None = None,
) -> TelegramLink:
    """Find or create the link from this Telegram account to a Curio profile.

    `adopt_profile_key` lets the Mini App hand over the anonymous profile the
    browser was already using, so someone who read the web app first and opened
    it inside Telegram later keeps their history instead of starting over.
    """
    link = await session.scalar(
        select(TelegramLink)
        .options(selectinload(TelegramLink.profile))
        .where(TelegramLink.telegram_id == user.id)
    )

    if link is None:
        profile: Profile | None = None
        if adopt_profile_key:
            profile = await session.scalar(
                select(Profile).where(Profile.key == adopt_profile_key)
            )
        if profile is None:
            profile = await personalization.get_or_create_profile(session, None)
            profile.display_name = user.display_name

        link = TelegramLink(telegram_id=user.id, profile_id=profile.id)
        # First contact sets the reading language from the Telegram client, so
        # a Russian-speaking reader is answered in Russian without having to
        # find a setting first. `/lang` overrides it permanently thereafter.
        link.locale = translation.normalise_locale(user.language_code)
        session.add(link)
        # The relationship is not populated by assigning the id alone, and the
        # caller needs the profile immediately.
        link.profile = profile

    link.username = user.username
    link.first_name = user.first_name
    link.language_code = user.language_code
    link.last_seen_at = datetime.now(timezone.utc)
    if chat_id is not None:
        link.chat_id = chat_id

    await session.flush()
    return link


def locale_of(link: TelegramLink) -> str:
    return translation.normalise_locale(link.locale or link.language_code)


def mode_of(link: TelegramLink) -> str:
    """Which lens this reader chose. Unset reads as the default."""
    return discovery.resolve_mode(link.mode)


# --- Card loading -----------------------------------------------------------


def _card_query():
    return select(Card).options(
        selectinload(Card.category),
        selectinload(Card.sources),
    )


async def _card_by_hex(session: AsyncSession, ident: str) -> Card | None:
    card_id = keyboards.uuid_from_hex(ident)
    if card_id is None:
        return None
    return await session.scalar(_card_query().where(Card.id == card_id))


async def _is_saved(session: AsyncSession, profile: Profile, card: Card) -> bool:
    saved = await personalization.saved_cards(session, profile)
    return any(existing.id == card.id for existing in saved)


# --- Sending ----------------------------------------------------------------


async def _send_card(
    session: AsyncSession,
    chat_id: int,
    profile: Profile,
    card: Card,
    *,
    locale: str,
    private: bool = True,
    show_another: bool = False,
) -> None:
    saved = await _is_saved(session, profile, card)
    # Interactions are recorded against the real card; only the rendering is
    # localized. The two must not be confused — a LocalCard is a view, not a row.
    await personalization.record_interaction(session, profile, card, kind="view")
    await discovery.record_view(session, card)

    if locale != translation.DEFAULT_LOCALE:
        await telegram.send_chat_action(chat_id)
    view = await localize.localize_preview(session, card, locale)

    await telegram.send_message(
        chat_id,
        render.truncate_message(render.card_intro(view, locale)),
        reply_markup=keyboards.card_keyboard(
            view,
            saved=saved,
            private=private,
            show_another=show_another,
            locale=locale,
        ),
    )


# --- Messages ---------------------------------------------------------------


async def _on_message(session: AsyncSession, message: dict) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    private = chat.get("type") == "private"
    raw_user = message.get("from") or {}
    if chat_id is None or not raw_user.get("id"):
        return

    user = parse_user(raw_user)
    link = await link_for(session, user, chat_id=chat_id if private else None)
    profile = link.profile
    locale = locale_of(link)

    text = (message.get("text") or "").strip()
    if not text:
        await telegram.send_message(chat_id, t(locale, "text_only"))
        return

    command, _, argument = text.partition(" ")
    command = command.lower()
    # Telegram appends @botname to commands sent in groups.
    if "@" in command:
        command = command.split("@", 1)[0]
    argument = argument.strip()

    if command == "/start":
        await _cmd_start(
            session,
            chat_id,
            profile,
            user,
            argument,
            locale=locale,
            private=private,
            mode=mode_of(link),
        )
    elif command == "/help":
        await telegram.send_message(
            chat_id, render.help_text(settings.telegram_bot_username, locale)
        )
    elif command in {"/lang", "/language"}:
        await _cmd_language(chat_id, locale)
    elif command == "/mode":
        await _cmd_mode(chat_id, mode_of(link), locale)
    elif command == "/random":
        await _cmd_random(
            session, chat_id, profile, locale=locale, private=private, mode=mode_of(link)
        )
    elif command == "/saved":
        await _cmd_saved(session, chat_id, profile, locale=locale, private=private)
    elif command == "/stats":
        await _cmd_stats(session, chat_id, profile, locale)
    elif command == "/search":
        await _cmd_search(
            session, chat_id, profile, argument, locale=locale, private=private
        )
    elif command.startswith("/"):
        await telegram.send_message(
            chat_id,
            t(locale, "unknown_command")
            + "\n\n"
            + render.help_text(settings.telegram_bot_username, locale),
        )
    else:
        # Anything else is treated as the question it probably is. In a group
        # that would mean answering every message, so there it stays quiet.
        if private:
            await _cmd_search(
                session, chat_id, profile, text, locale=locale, private=private
            )


async def _cmd_start(
    session: AsyncSession,
    chat_id: int,
    profile: Profile,
    user: TelegramUser,
    payload: str,
    *,
    locale: str,
    private: bool,
    mode: str = discovery.DEFAULT_MODE,
) -> None:
    # Deep link: t.me/<bot>?start=c<card id hex> opens straight to a card, which
    # is what the "share" links in the web app point at.
    if payload.startswith("c") and len(payload) == 33:
        card = await _card_by_hex(session, payload[1:])
        if card is not None:
            await _send_card(session, chat_id, profile, card, locale=locale, private=private)
            return

    await telegram.send_message(
        chat_id,
        render.welcome(
            user.first_name,
            locale=locale,
            bot_username=settings.telegram_bot_username,
        ),
        reply_markup=keyboards.start_keyboard(locale, mode) if private else None,
    )


async def _cmd_language(chat_id: int, locale: str) -> None:
    text = t(locale, "language_prompt")
    if not translation.enabled():
        text += "\n\n" + t(locale, "language_unavailable")
    await telegram.send_message(
        chat_id, text, reply_markup=keyboards.language_keyboard(locale)
    )


async def _cmd_mode(chat_id: int, mode: str, locale: str) -> None:
    await telegram.send_message(
        chat_id,
        t(locale, "mode_prompt"),
        reply_markup=keyboards.mode_keyboard(mode, locale),
    )


async def _cmd_random(
    session: AsyncSession,
    chat_id: int,
    profile: Profile,
    *,
    locale: str,
    private: bool,
    mode: str = discovery.DEFAULT_MODE,
) -> None:
    picked = await discovery.random_card(session, profile=profile, mode=mode)
    if picked is None and mode != discovery.DEFAULT_MODE:
        # Better to answer with something than to leave a reader who picked
        # useful mode with nothing at all while the corpus is still filling up.
        await telegram.send_message(chat_id, t(locale, "mode_empty_useful"))
        picked = await discovery.random_card(session, profile=profile)
    if picked is None:
        await telegram.send_message(chat_id, t(locale, "empty_library"))
        return
    # random_card loads the category but not the sources the 📚 button needs.
    card = await session.scalar(_card_query().where(Card.id == picked.id))
    if card is None:
        return
    await _send_card(
        session, chat_id, profile, card, locale=locale, private=private, show_another=True
    )


async def _cmd_search(
    session: AsyncSession,
    chat_id: int,
    profile: Profile,
    query: str,
    *,
    locale: str,
    private: bool,
) -> None:
    query = query.strip()
    if len(query) < MIN_QUERY_LENGTH:
        await telegram.send_message(chat_id, t(locale, "query_too_short"))
        return

    await telegram.send_chat_action(chat_id)

    # The index and the embeddings are both built from English cards, so a
    # Russian question is translated before it is searched. The reader is told,
    # because otherwise the results look unrelated to what they typed.
    searched = await translation.to_english(session, query)
    note = (
        t(locale, "searching_translated", query=searched)
        if searched.strip().lower() != query.strip().lower()
        else ""
    )

    hits = await search_service.hybrid_search(session, searched, limit=SEARCH_RESULTS)
    cards = [hit.card for hit in hits]

    if not cards:
        await telegram.send_message(
            chat_id,
            render.results_list([], query=query, locale=locale),
            reply_markup=keyboards.results_keyboard([], private=private, locale=locale),
        )
        return

    if len(cards) == 1:
        await _send_card(session, chat_id, profile, cards[0], locale=locale, private=private)
        return

    views = await localize.localize_previews(session, cards, locale)
    await telegram.send_message(
        chat_id,
        render.truncate_message(
            render.results_list(views, query=query, locale=locale, note=note)
        ),
        reply_markup=keyboards.results_keyboard(views, private=private, locale=locale),
    )


async def _cmd_saved(
    session: AsyncSession, chat_id: int, profile: Profile, *, locale: str, private: bool
) -> None:
    cards = await personalization.saved_cards(session, profile)
    if not cards:
        await telegram.send_message(chat_id, t(locale, "nothing_saved"))
        return

    shown = cards[:10]
    views = await localize.localize_previews(session, shown, locale)
    await telegram.send_message(
        chat_id,
        render.truncate_message(
            render.results_list(views, query=t(locale, "saved_heading"), locale=locale)
        ),
        reply_markup=keyboards.results_keyboard(views, private=private, locale=locale),
    )


async def _cmd_stats(
    session: AsyncSession, chat_id: int, profile: Profile, locale: str
) -> None:
    data = await personalization.stats(session, profile)
    await telegram.send_message(
        chat_id,
        (
            f"📊 <b>{t(locale, 'stats_heading')}</b>\n\n"
            f"{t(locale, 'stats_read')}: <b>{data['cards_read']}</b>\n"
            f"{t(locale, 'stats_saved')}: <b>{data['cards_saved']}</b>\n"
            f"{t(locale, 'stats_completed')}: <b>{data['cards_completed']}</b>\n"
            f"{t(locale, 'stats_concepts')}: <b>{data['concepts_explored']}</b>\n"
            f"{t(locale, 'stats_time')}: "
            f"<b>{t(locale, 'stats_minutes', n=data['minutes_learning'])}</b>\n"
            f"{t(locale, 'stats_streak')}: "
            f"<b>{t(locale, 'stats_days', n=data['streak_days'])}</b> "
            f"({t(locale, 'stats_best', n=data['longest_streak'])})"
        ),
    )


# --- Callback queries -------------------------------------------------------


async def _on_callback(session: AsyncSession, query: dict) -> None:
    callback_id = query.get("id")
    data = query.get("data") or ""
    message = query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    private = chat.get("type") == "private"
    raw_user = query.get("from") or {}

    if not callback_id:
        return
    if data == keyboards.NOOP or chat_id is None or message_id is None:
        await telegram.answer_callback(callback_id)
        return

    user = parse_user(raw_user)
    link = await link_for(session, user, chat_id=chat_id if private else None)
    profile = link.profile
    locale = locale_of(link)

    verb, ident, argument = keyboards.parse(data)

    if verb == "r":
        await telegram.answer_callback(callback_id)
        await _cmd_random(
            session, chat_id, profile, locale=locale, private=private, mode=mode_of(link)
        )
        return

    if verb == "w":
        # `w` alone opens the picker; `w:<mode>` is a choice.
        if not ident:
            await telegram.answer_callback(callback_id)
            await _cmd_mode(chat_id, mode_of(link), locale)
            return

        chosen = discovery.resolve_mode(ident)
        link.mode = chosen
        await session.commit()
        await telegram.answer_callback(callback_id, t(locale, f"mode_set_{chosen}"))
        await telegram.edit_message(
            chat_id,
            message_id,
            t(locale, "mode_prompt"),
            reply_markup=keyboards.mode_keyboard(chosen, locale),
        )
        return

    if verb == "g":
        # `g` alone opens the picker; `g:<locale>` is a choice.
        if not ident:
            await telegram.answer_callback(callback_id)
            await _cmd_language(chat_id, locale)
            return

        chosen = translation.normalise_locale(ident)
        link.locale = chosen
        await session.commit()
        await telegram.answer_callback(callback_id, t(chosen, "language_set"))
        confirmation = t(chosen, "language_prompt")
        if not translation.enabled():
            confirmation += "\n\n" + t(chosen, "language_unavailable")
        await telegram.edit_message(
            chat_id,
            message_id,
            confirmation,
            reply_markup=keyboards.language_keyboard(chosen),
        )
        return

    card = await _card_by_hex(session, ident)
    if card is None:
        await telegram.answer_callback(callback_id, t(locale, "card_gone"), alert=True)
        return

    saved = await _is_saved(session, profile, card)

    if verb == "s":
        kind = "unsave" if saved else "save"
        await personalization.record_interaction(session, profile, card, kind=kind)
        saved = not saved
        await telegram.answer_callback(
            callback_id, t(locale, "toast_saved" if saved else "toast_removed")
        )
        # Only the button label changes, so the message text is left alone:
        # rewriting it would collapse whichever view the reader is looking at.
        await telegram.edit_markup(
            chat_id,
            message_id,
            await _current_keyboard(
                session, card, message, saved=saved, private=private, locale=locale
            ),
        )
        await session.commit()
        return

    await telegram.answer_callback(callback_id)

    # A translation may take a second or two on a cold card; the typing
    # indicator is the only signal available on an edit.
    if locale != translation.DEFAULT_LOCALE:
        await telegram.send_chat_action(chat_id)

    if verb == "c":
        view = await localize.localize_preview(session, card, locale)
        text = render.card_intro(view, locale)
        markup = keyboards.card_keyboard(
            view, saved=saved, private=private, locale=locale
        )
    elif verb == "l":
        total = render.level_count(card)
        level = max(1, min(argument or 1, total or 1))
        view = await localize.localize_level(session, card, locale, level)
        text = render.level_view(view, level, locale)
        markup = keyboards.card_keyboard(
            view, level=level, saved=saved, private=private, locale=locale
        )
        await personalization.record_interaction(
            session, profile, card, kind="level_reached", level=level
        )
        if total and level == total:
            await personalization.record_interaction(
                session, profile, card, kind="complete", level=level
            )
    elif verb == "t":
        view = await localize.localize_terms(session, card, locale)
        text = render.terms_view(view, locale)
        markup = keyboards.section_keyboard(
            view, saved=saved, private=private, locale=locale
        )
    elif verb == "m":
        view = await localize.localize_myths(session, card, locale)
        text = render.myths_view(view, locale)
        markup = keyboards.section_keyboard(
            view, saved=saved, private=private, locale=locale
        )
    elif verb == "x":
        view = await localize.localize_sources(session, card, locale)
        text = render.sources_view(view, locale)
        markup = keyboards.section_keyboard(
            view, saved=saved, private=private, locale=locale
        )
    else:
        return

    await telegram.edit_message(
        chat_id, message_id, render.truncate_message(text), reply_markup=markup
    )


async def _current_keyboard(
    session: AsyncSession,
    card: Card,
    message: dict,
    *,
    saved: bool,
    private: bool,
    locale: str,
) -> dict:
    """Rebuild the keyboard for whichever view a message is currently showing.

    Save is reachable from every view and must not move the reader out of the
    one they are in. The state is recovered from the buttons already on the
    message rather than tracked server-side, so a message from last week still
    behaves correctly after a restart.

    Three shapes are distinguishable: a level view has the inert `n/m` counter,
    a section view (terms, myths, sources) has no level buttons at all, and the
    preview has a level button but no counter.
    """
    rows = (message.get("reply_markup") or {}).get("inline_keyboard") or []
    buttons = [button for row in rows for button in row]

    for button in buttons:
        label = button.get("text", "")
        if button.get("callback_data") == keyboards.NOOP and "/" in label:
            head = label.split("/", 1)[0]
            if head.isdigit():
                level = int(head)
                view = await localize.localize_level(session, card, locale, level)
                return keyboards.card_keyboard(
                    view, level=level, saved=saved, private=private, locale=locale
                )

    has_level_button = any(
        button.get("callback_data", "").startswith("l:") for button in buttons
    )
    if not has_level_button:
        view = await localize.localize_preview(session, card, locale)
        return keyboards.section_keyboard(
            view, saved=saved, private=private, locale=locale
        )

    view = await localize.localize_preview(session, card, locale)
    return keyboards.card_keyboard(view, saved=saved, private=private, locale=locale)


# --- Inline mode ------------------------------------------------------------


async def _on_inline(session: AsyncSession, query: dict) -> None:
    inline_id = query.get("id")
    text = (query.get("query") or "").strip()
    if not inline_id:
        return

    # Inline queries come with no chat and no stored link, so the language is
    # whatever the sender's client reports.
    raw_user = query.get("from") or {}
    locale = translation.normalise_locale(raw_user.get("language_code"))
    link = await session.scalar(
        select(TelegramLink).where(TelegramLink.telegram_id == raw_user.get("id", 0))
    )
    if link is not None and link.locale:
        locale = translation.normalise_locale(link.locale)

    if len(text) < MIN_QUERY_LENGTH:
        cards = await discovery.shelf_cards(session, "everyone-asks", limit=8)
    else:
        searched = await translation.to_english(session, text)
        hits = await search_service.hybrid_search(session, searched, limit=10)
        cards = [hit.card for hit in hits]

    views = await localize.localize_previews(session, cards[:10], locale)

    results = []
    for view in views:
        markup = keyboards.inline_result_keyboard(view, locale)
        results.append(
            {
                "type": "article",
                "id": view.id.hex,
                "title": view.title[:100],
                "description": view.one_sentence_answer[:180],
                "input_message_content": {
                    "message_text": render.truncate_message(
                        render.card_intro(view, locale)
                    ),
                    "parse_mode": "HTML",
                    "link_preview_options": {"is_disabled": True},
                },
                **({"reply_markup": markup} if markup else {}),
            }
        )

    button = None
    if settings.telegram_webapp_ready:
        button = {
            "text": t(locale, "btn_open_app"),
            "web_app": {"url": settings.telegram_webapp_url.rstrip("/")},
        }

    await telegram.answer_inline(inline_id, results, cache_time=60, button=button)


# --- Entry point ------------------------------------------------------------


async def handle_update(session: AsyncSession, update: dict) -> None:
    """Route one Telegram update. Never raises — see the webhook route."""
    try:
        if "message" in update:
            await _on_message(session, update["message"])
        elif "callback_query" in update:
            await _on_callback(session, update["callback_query"])
        elif "inline_query" in update:
            await _on_inline(session, update["inline_query"])
        else:
            return
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("telegram update %s failed", update.get("update_id"))
