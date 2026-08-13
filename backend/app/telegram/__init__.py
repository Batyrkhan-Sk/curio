"""Curio inside Telegram.

Two surfaces over the same corpus and the same reader profile:

* the **chat bot** — `/random`, `/search`, inline queries, and a card read
  level by level through inline-keyboard navigation, all inside the chat;
* the **Mini App** — the ordinary Next.js frontend opened in Telegram's
  webview, authenticated by the signed `initData` the client passes in.

Both resolve to one `Profile` via `TelegramLink`, so a card saved from a chat
message is on the Saved page when the Mini App opens.
"""
