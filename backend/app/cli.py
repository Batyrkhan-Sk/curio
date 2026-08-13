"""Operational commands.

    docker compose run --rm api python -m app.cli vapid
    docker compose run --rm api python -m app.cli seed [--force]
    docker compose run --rm api python -m app.cli ingest [--discover-only]
    docker compose run --rm api python -m app.cli synthesize "Why is the sky blue?"
    docker compose run --rm api python -m app.cli reindex
    docker compose run --rm api python -m app.cli reshelve
    docker compose run --rm api python -m app.cli telegram [setup|info|delete]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("curio.cli")


def generate_vapid() -> dict[str, str]:
    """Generate a VAPID keypair in the URL-safe base64 form browsers expect."""
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_numbers = private_key.public_key().public_numbers()

    # Uncompressed point format: 0x04 || X || Y — what applicationServerKey wants.
    raw_public = (
        b"\x04"
        + public_numbers.x.to_bytes(32, "big")
        + public_numbers.y.to_bytes(32, "big")
    )
    raw_private = private_key.private_numbers().private_value.to_bytes(32, "big")

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    return {"public_key": b64(raw_public), "private_key": b64(raw_private)}


async def cmd_seed(force: bool) -> None:
    from app.core.db import SessionLocal, init_models
    from app.db.seed import seed_all

    await init_models()
    async with SessionLocal() as session:
        result = await seed_all(session, force=force)
    print(json.dumps(result, indent=2))


async def cmd_ingest(
    discover_only: bool, max_cards: int | None, practical_first: bool
) -> None:
    from app.core.db import SessionLocal, init_models
    from app.ingestion import runner

    await init_models()
    async with SessionLocal() as session:
        report = (
            await runner.discover(session)
            if discover_only
            else await runner.full_run(
                session, max_cards=max_cards, practical_first=practical_first
            )
        )
    print(json.dumps(report.as_dict(), indent=2))


async def cmd_synthesize(question: str) -> None:
    from app.ai import pipeline
    from app.core.db import SessionLocal, init_models

    await init_models()
    async with SessionLocal() as session:
        try:
            result = await pipeline.synthesize(session, question, origin="manual")
        except pipeline.PipelineDisabled as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    print(
        json.dumps(
            {
                "slug": result.card.slug,
                "title": result.card.title,
                "published": result.published,
                "confidence": result.confidence,
                "notes": result.notes,
            },
            indent=2,
        )
    )


async def cmd_providers() -> None:
    """Report which providers are configured and what they can actually run."""
    from app.ai import quota
    from app.ai.gemini import gemini
    from app.ai.llm import llm
    from app.ai.openai_compat import groq, xai

    print("Provider order:", ", ".join(p["name"] for p in llm.describe()))
    for spec in llm.describe():
        mark = "configured" if spec["configured"] else "no key"
        embeds = " (provides embeddings)" if spec["embeddings"] else ""
        print(f"  {spec['name']:8} {mark:12} model={spec['model']}{embeds}")

    for client, label in ((gemini, "gemini"), (groq, "groq"), (xai, "xai")):
        if not client.enabled:
            continue
        try:
            reply = await client.generate("Reply with exactly: OK", temperature=0)
            print(f"\n{label}: live — {reply.strip()[:40]}")
        except Exception as exc:
            print(f"\n{label}: FAILED — {type(exc).__name__}: {str(exc)[:160]}")

    exhausted = quota.snapshot()
    if exhausted:
        print("\nOut of daily quota until:")
        for key, when in exhausted.items():
            print(f"  {key:44} {when}")


BOT_COMMANDS = [
    {"command": "random", "description": "A card picked for no reason at all"},
    {"command": "mode", "description": "Interesting, or useful in life"},
    {"command": "search", "description": "Find a question — or just send it"},
    {"command": "saved", "description": "The cards you kept"},
    {"command": "stats", "description": "What you have read"},
    {"command": "lang", "description": "Reading language / Язык чтения"},
    {"command": "help", "description": "What this bot can do"},
]

BOT_COMMANDS_RU = [
    {"command": "random", "description": "Случайная карточка, без всякого повода"},
    {"command": "mode", "description": "Интересное или полезное в жизни"},
    {"command": "search", "description": "Найти вопрос — или просто пришлите его"},
    {"command": "saved", "description": "Сохранённые карточки"},
    {"command": "stats", "description": "Что вы прочитали"},
    {"command": "lang", "description": "Язык чтения"},
    {"command": "help", "description": "Что умеет этот бот"},
]

BOT_DESCRIPTION = (
    "Curio indexes the questions people keep asking rather than the pages that "
    "answer them badly. Every card starts at plain intuition and goes five "
    "levels down to expert detail, names the misconceptions, and shows its "
    "sources. Send me anything you are curious about."
)

BOT_SHORT_DESCRIPTION = "The questions people keep asking, properly answered."


async def cmd_telegram(action: str) -> None:
    """Apply everything about the bot that lives on Telegram's side.

    BotFather creates the bot and hands over a token; the commands list, the
    menu button, and the webhook are all set through the API, so they belong in
    code rather than in a chat transcript nobody can replay.
    """
    import secrets as _secrets

    from app.core.config import settings
    from app.services import telegram

    if not settings.telegram_bot_token:
        print(
            "TELEGRAM_BOT_TOKEN is not set.\n\n"
            "  1. Open @BotFather in Telegram and send /newbot\n"
            "  2. Put the token it gives you in .env as TELEGRAM_BOT_TOKEN\n"
            "  3. Run this again",
            file=sys.stderr,
        )
        raise SystemExit(1)

    me = await telegram.get_me()
    print(f"Bot: @{me.get('username')} ({me.get('id')})")

    if action == "info":
        info = await telegram.get_webhook_info()
        print(json.dumps(info, indent=2))
        return

    if action == "delete":
        await telegram.delete_webhook()
        print("Webhook removed. The bot will not receive updates until you set it again.")
        return

    # --- setup ------------------------------------------------------------
    await telegram.set_my_commands(BOT_COMMANDS)
    # Telegram picks the list by the *client's* language, independently of the
    # reading language the bot stores — so a Russian client sees Russian command
    # hints before ever sending /start.
    await telegram.set_my_commands(BOT_COMMANDS_RU, language_code="ru")
    print(f"Commands set ({len(BOT_COMMANDS)}), English and Russian.")

    await telegram.set_my_description(BOT_DESCRIPTION, BOT_SHORT_DESCRIPTION)
    print("Description set.")

    if settings.telegram_webapp_ready:
        await telegram.set_chat_menu_button(settings.telegram_webapp_url.rstrip("/"))
        print(f"Menu button opens the Mini App at {settings.telegram_webapp_url}")
    else:
        await telegram.set_chat_menu_button(None)
        print(
            "Menu button left as the command list — TELEGRAM_WEBAPP_URL is "
            f"{settings.telegram_webapp_url or 'unset'} and a Mini App needs an "
            "https:// origin. Start a tunnel and set it to get the reader button."
        )

    public = settings.telegram_public_url.rstrip("/")
    if not public:
        print(
            "\nTELEGRAM_PUBLIC_URL is unset, so the webhook was not registered.\n"
            "Set it to the public https origin of this API and run this again.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not public.startswith("https://"):
        print(
            f"\nTELEGRAM_PUBLIC_URL is {public!r}. Telegram only delivers to "
            "https, so the webhook was not registered.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    secret = settings.telegram_webhook_secret
    generated = False
    if not secret:
        secret = _secrets.token_urlsafe(32)
        generated = True

    url = f"{public}/api/v1/telegram/webhook"
    await telegram.set_webhook(url, secret)
    print(f"Webhook registered: {url}")

    if generated:
        print(
            "\nA webhook secret was generated. Add it to .env and restart the "
            "API, or Telegram's updates will be rejected:\n\n"
            f"TELEGRAM_WEBHOOK_SECRET={secret}"
        )

    print(f"\nOpen https://t.me/{me.get('username')} and send /start.")


async def cmd_reshelve() -> None:
    """Recompute every card's shelf membership from its own properties.

    Shelves are written once, when a card is created. That is right for a
    static rule and wrong the moment the rule changes: cards ingested before
    "worth-knowing" existed kept the shelves they were born with and never
    joined it, however practical they were. This is the way back.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.db import SessionLocal
    from app.models import Card
    from app.services import discovery

    recent = datetime.now(timezone.utc) - timedelta(days=3)
    changed = 0
    moved: dict[str, int] = {}

    async with SessionLocal() as session:
        rows = await session.execute(
            select(Card).options(selectinload(Card.category))
        )
        cards = list(rows.scalars().unique())

        for card in cards:
            before = set(card.shelves or [])
            after = discovery.shelves_for_card(
                card,
                # "Today's discoveries" is the one shelf that is about when the
                # card arrived rather than what it says, so it is preserved on
                # its own terms instead of being recomputed as true for all.
                is_new=card.origin != "curated"
                and card.created_at is not None
                and card.created_at >= recent,
            )
            if before == set(after):
                continue
            card.shelves = after
            changed += 1
            for key in set(after) - before:
                moved[key] = moved.get(key, 0) + 1

        await session.commit()

    print(json.dumps(
        {"cards": len(cards), "changed": changed, "gained": dict(sorted(moved.items()))},
        indent=2,
    ))


async def cmd_reindex() -> None:
    from app.core.db import SessionLocal
    from app.services import search

    await search.ensure_index()
    async with SessionLocal() as session:
        count = await search.reindex_all(session)
    print(json.dumps({"indexed": count}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli", description="Curio operations")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("vapid", help="Generate a VAPID keypair for web push")

    seed = sub.add_parser("seed", help="Load the curated corpus")
    seed.add_argument("--force", action="store_true", help="Overwrite existing cards")

    ingest = sub.add_parser("ingest", help="Run a discovery pass")
    ingest.add_argument(
        "--discover-only", action="store_true", help="Collect questions but do not synthesise"
    )
    ingest.add_argument(
        "--max-cards", type=int, default=None, help="Override INGESTION_MAX_NEW_CARDS"
    )
    ingest.add_argument(
        "--practical-first",
        action="store_true",
        help="Prefer questions whose answers have consequences, to stock useful mode",
    )

    synth = sub.add_parser("synthesize", help="Write a card for one question")
    synth.add_argument("question")

    sub.add_parser("reindex", help="Rebuild the Meilisearch index")
    sub.add_parser("reshelve", help="Recompute shelf membership for every card")
    sub.add_parser("providers", help="Show and probe the configured AI providers")

    tg = sub.add_parser("telegram", help="Register the bot's webhook, commands and menu")
    tg.add_argument(
        "action",
        nargs="?",
        default="setup",
        choices=["setup", "info", "delete"],
        help="setup (default) applies everything; info shows Telegram's view; "
        "delete unregisters the webhook",
    )

    args = parser.parse_args()

    if args.command == "vapid":
        keys = generate_vapid()
        print("Add these to your .env:\n")
        print(f"VAPID_PUBLIC_KEY={keys['public_key']}")
        print(f"VAPID_PRIVATE_KEY={keys['private_key']}")
        return

    runners = {
        "seed": lambda: cmd_seed(args.force),
        "ingest": lambda: cmd_ingest(
            args.discover_only, args.max_cards, args.practical_first
        ),
        "synthesize": lambda: cmd_synthesize(args.question),
        "reindex": cmd_reindex,
        "reshelve": cmd_reshelve,
        "providers": cmd_providers,
        "telegram": lambda: cmd_telegram(args.action),
    }
    asyncio.run(runners[args.command]())


if __name__ == "__main__":
    main()
