# Curio

**Indexing human curiosity rather than web pages.**

Google indexes pages. Wikipedia organises knowledge by topic. Curio organises
it by the questions people keep asking — because the question is usually the
part you already have, and the page is the part you have to go and find.

Every question becomes a knowledge card that starts at plain intuition a
12-year-old could follow and goes down five levels to expert detail, names the
misconceptions, shows its sources, and states how confident it is.

## Deploy:

Ask questions in telegram bot: https://t.me/curio_to_know_bot

Explore questions in the website: https://curio.tail76c5ea.ts.net

---

## Running it

```bash
cp .env.example .env
docker compose up -d
```

Then open **http://localhost:3001**.

On first boot the API creates the schema, seeds a curated corpus of fifty-nine
fully written cards, builds the knowledge graph between them, and indexes
everything into Meilisearch. Nothing else is required — **no API key is needed
to run the platform.**

The curated corpus in `backend/app/db/seed/` is hand-written and checked in, not
scraped. Questions collected from the public internet arrive through a separate
route — the ingestion pipeline — and are marked `origin: ingested` rather than
`curated`. Every card says which it is: the **Where this question came from**
section names the forum and links the threads it was observed in, or states
plainly that it was written rather than found.

| Service | URL | Purpose |
| --- | --- | --- |
| Web | http://localhost:3001 | Next.js frontend / installable PWA |
| API | http://localhost:8000/docs | FastAPI, with generated OpenAPI docs |
| Meilisearch | http://localhost:7700 | Keyword search |
| Postgres | localhost:5433 | Data + pgvector embeddings |

> The web port is 3001 rather than 3000 to avoid colliding with another dev
> server. Change `WEB_PORT` in `.env` if you would rather have 3000.

---

## What works without an AI key, and what doesn't

This split is deliberate. The platform is fully usable with `GEMINI_API_KEY`
empty; the AI features are additive rather than load-bearing.

| | No key | With a Gemini key |
| --- | --- | --- |
| Browse, shelves, cards, graph | ✅ | ✅ |
| Keyword search (typo-tolerant, synonyms) | ✅ | ✅ |
| Search by meaning | — | ✅ pgvector + hybrid ranking |
| Saves, offline reading, install, push | ✅ | ✅ |
| Personalisation and recommendations | ✅ | ✅ |
| "I still don't understand" | ✅ falls back to the card's other levels | ✅ generates a genuinely new framing |
| Discovering new questions from the internet | — | ✅ |
| Writing new cards | — | ✅ |

To switch the AI on, set `GEMINI_API_KEY` in `.env` and restart.

### Providers and failover

`LLM_PROVIDER_ORDER` (default `gemini,groq,xai`) is a chain, not a single choice.
Each provider is tried in turn and the next takes over when one is out of
quota, misconfigured, or persistently failing — so a dead daily allowance
degrades to the fallback instead of stopping the pipeline.

```bash
docker compose run --rm api python -m app.cli providers   # probe both, list models
```

Supported providers:

| Key | Provider | Notes |
| --- | --- | --- |
| `GEMINI_API_KEY` | Google Gemini | The only one with embeddings, so it leads |
| `GROQ_API_KEY` | **Groq** — api.groq.com, keys start `gsk_` | Fast inference over open models |
| `XAI_API_KEY` | **xAI (Grok)** — api.x.ai | A different company; easily confused |

> Groq and Grok are not the same thing. A `gsk_` key sent to `api.x.ai` is
> rejected with "Incorrect API key provided", which is a confusing way to
> discover you filled in the wrong variable.

Two things do not fail over:

* **Embeddings.** Neither Groq nor xAI offers an embeddings endpoint, and
  vectors from two different models occupy different spaces — a half-and-half
  index returns nonsense from every similarity query. Embeddings stay on
  Gemini, and semantic search switches off rather than degrading invisibly.
* **Model ids.** Every `*_MODEL` is a plain config value. Point them at
  whatever your keys actually have.

Per-provider limits differ in kind, so the ceilings are set separately.
`LLM_MAX_OUTPUT_TOKENS` is 32768 for Gemini because thinking tokens come out of
the same budget; `GROQ_MAX_OUTPUT_TOKENS` is 6000 because Groq's free tier caps
a whole request at 8000 tokens per *minute* and rejects anything larger with a
413 before the model sees it.

Long batches are paced by `INGESTION_PAUSE_SECONDS` (default 20) for the same
reason — per-minute token ceilings will stop a run otherwise.

### Quotas and reasoning models

Two things will bite you on a free tier, and both are handled explicitly:

* **Per-day quotas.** Gemini's free tier allows a small number of
  `generateContent` requests per day *per model* — 20 at the time of writing.
  A daily exhaustion is detected from the 429 body and raised as
  `LLMQuotaExceeded`, which is **not** retried: every retry against a dead
  daily quota is another wasted request. The batch stops and reports why.
* **Thinking tokens.** Gemini 3.x models reason before answering, and those
  tokens count against `maxOutputTokens`. A card needs roughly 4k tokens of
  JSON, and a reasoning model can spend several thousand more before writing
  any of it — so the default ceiling is `LLM_MAX_OUTPUT_TOKENS=32768` and
  `GEMINI_THINKING_LEVEL=low`. Truncation is detected from `finishReason` and
  reported as itself, rather than surfacing much later as an unterminated JSON
  string.

---

## Architecture

```
frontend/          Next.js 16 · React 19 · Tailwind v4 · TypeScript
  src/app/           routes (discovery, card, graph, categories, saved, you)
  src/components/    ui primitives, card reader, discovery shelves, graph, PWA
  src/lib/           typed API client, offline store (IndexedDB), utils
  public/sw.js       service worker: offline shell, API cache, push

backend/           FastAPI · SQLAlchemy 2 async · Postgres + pgvector
  app/ai/            Gemini client, prompts, synthesis pipeline, re-explanation
  app/ingestion/     source collectors, dedupe, evidence retrieval, runner
  app/services/      search, embeddings, graph, discovery, personalisation, push
  app/api/v1/        routers
  app/db/seed/       the curated corpus
```

### The pipeline

The seventeen stages from the product brief map onto the code as follows:

| Stages | Where |
| --- | --- |
| 1–2 detect repeated curiosity, merge duplicates | `ingestion/dedupe.py` — exact match, then pg_trgm similarity, then embedding distance |
| 3a structural rejection (no AI needed) | `ingestion/triage.py` — drops personal essays, news, opinion, and support requests that merely begin with "why" |
| 3 identify the underlying concept | `ai/pipeline.py::triage_questions` |
| 4 retrieve reliable sources | `ingestion/evidence.py` — Wikipedia, arXiv, Stack Exchange, HN |
| 5–7 compare, detect contradictions, verify | `ai/pipeline.py::verify` |
| 8–15 generate answer, levels, analogies, diagrams, examples, misconceptions | `ai/pipeline.py::synthesize` |
| 16 connect related concepts | `services/graph.py` — shared concepts, then vector similarity |
| 17 recommend what to learn next | `services/personalization.py::next_in_learning_path` |

The two triage stages split the work by what each is actually good at.
`ingestion/triage.py` is pure regex and rejects on *structure* — "Why I quit
Google" is a personal essay no matter how many upvotes it has. What survives
still needs a judgement about whether it is *interesting*, and that is what the
model does. On a real run of 363 collected questions the structural pass
rejected 232 and passed 131 through.

### Where the questions come from

`ingestion/sources/forums.py` collects from four public sources: Hacker News
via the Algolia index, eighteen question-shaped subreddits, sixteen Stack
Exchange sites including Stack Overflow, and Habr — the Russian IT community,
covered separately below. The lists deliberately mix the
interesting with the useful — r/askscience and r/explainlikeimfive alongside
r/personalfinance, r/HomeImprovement and money.stackexchange — because the
**Worth knowing before you need it** shelf needs questions whose answers change
what someone does, not only what they find interesting.

Reddit needs one accommodation. It now answers its public JSON feed with a 403
block page from most datacentre addresses, so the collector falls back to the
Atom feed, which is still served to browser-like agents. The Atom feed carries
no score, but a question observed in several places accumulates engagement
through the dedupe merge instead.

Reddit then throttles that feed with a bare 429 — no `Retry-After`, no body —
and refills the budget erratically, so a fixed pause is not enough on its own.
Each subreddit is paced by `REDDIT_PAUSE_SECONDS` and retried `REDDIT_RETRIES`
times with a growing wait; without the retries a run harvests one subreddit and
gives up on the rest — with them, twelve of thirteen.

Setting `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` (a free "script" app at
<https://www.reddit.com/prefs/apps>) switches the collector to the authenticated
API instead: 100 requests a minute, no pacing, and scores and comment counts
included for engagement ranking.

You can watch this happen at **`/incoming`**, which lists every question the
platform has collected, what it came from, how many places it was asked in, and
whether it was rejected, is still waiting, or became a card.

#### Habr, and the cost of a non-English source

`ingestion/sources/habr.py` adds the Russian IT community. It is the only
source that is not in English, which makes it the one that had to answer two
questions the others never raise.

**What survives the filter.** The English collectors run on "anything
question-shaped, minus obvious noise", because a curated subreddit already asks
durable questions. Habr Q&A is not that: it is working developers whose build
is broken tonight. On the permissive setting it passed **21 of 21** on a live
page — kernel panics, dead motherboards, "Chrome cleared my cache, what do I
do". So Russian text is filtered on reversed polarity: it must *positively*
open like a question about how something works (`почему`, `как работает`, `в
чём разница`, `правда ли`) and must carry none of the marks of a support
request. On a 37-question sample across six pages of "Интересные вопросы", that
correctly kept none — every one was support, shopping, or somebody's own
situation. That is the source, not the filter.

Article titles get a looser rule, because an editorial headline is written to
be read rather than answered: the question often arrives mid-line and opens
with verbs the strict test excludes. Requiring the durable opening at position
zero rejected **0 of 80** across two feeds. `looks_like_question_headline`
takes a question mark plus a question word anywhere instead, and the headline
is then trimmed to the question inside it — `[Перевод] Спросите Итана: Стоит ли
нам перестать беспокоиться о распаде вакуума?` is a card titled *Should we stop
worrying about vacuum decay?*, not a column name and a translation tag.

Yields differ by an order of magnitude between hubs. Popular science, physics
and astronomy ask durable questions in their titles; programming and
infosecurity almost never do. Both kinds are polled anyway — a thin trickle
from the IT hubs is still the right kind of thing.

**What language it lands in.** The index, the embeddings, and both AI prompts
are English, so a Russian question in an English pool matches nothing and
duplicates everything. Collected questions are therefore translated on the way
in, through the same cached engine the Telegram bot reads with. The original
wording is kept on `Question.original_text` and is what the card cites, because
quoting somebody in words they never used is not a citation.

If translation is unavailable the question enters the pool in Russian and
triage will almost certainly reject it — which is the correct outcome, and a
better one than dropping the whole harvest because a quota ran out.

A live run: 9 questions collected, 9 translated, 6 new and 3 merged into
existing ones by the embedding dedupe.

```
Как получаются нейтронные звёзды?              → How are neutron stars formed?
Что будет, если разрезать фотон пополам?       → What happens if you cut a photon in half?
Отпечатки браузера: что это такое и как работает?
                                               → Browser fingerprinting: what is it and how does it work?
```

Habr publishes no documented API. Q&A has an RSS feed linked from its own pages
that appears in no documentation, and the listings are server-rendered HTML —
so the collector scrapes the listing ordered the way we want and falls back to
the feed ordered the way it is. Neither is allowed to raise.

### The shelves

The homepage is queries, not editorial lists. Most shelves sort on properties a
card already has — misconception count, reading time, curiosity score — and one
is worth calling out because it answers a different question from the rest:

**Worth knowing before you need it** collects cards whose answer changes what
someone does rather than only what they know: why water makes a pan fire worse,
why a paracetamol overdose is dangerous while you still feel fine, why braking
distance quadruples rather than doubles. Membership is derived from a narrow tag
vocabulary in `services/discovery.py::PRACTICAL_TAGS`, and narrow is the whole
design — an earlier version included `energy`, which every second physics card
carries, and the shelf about saving people money began recommending special
relativity.

Every stage degrades rather than fails. If verification cannot run, the card
is published with a low confidence score and flagged — it is never published
claiming a confidence it did not earn. Below `MIN_PUBLISH_CONFIDENCE` (0.45) it
is not published at all.

### The one unbreakable rule

No card may use a term it has not already explained. This is enforced in three
places: the house-style prompt, the verification pass (which lists jargon
violations and docks confidence for each), and the `key_terms` field that every
card must populate. It is the difference between an answer you can read and an
answer you have to go and research first.

---

## Search

Meilisearch alone cannot find the Wi-Fi wall-attenuation card from "wifi weak
bedroom". Vectors alone are vague about exact terms and typos. So both run and
their rankings are fused with Reciprocal Rank Fusion (`services/search.py`).
With no AI key the vector half simply drops out and keyword search carries on.

---

## Mobile

The frontend is an installable PWA — one codebase for phone and desktop.

- **Android / Chrome / Edge / desktop** — `beforeinstallprompt` is captured and
  a real Install button is shown.
- **iOS Safari** — no programmatic install exists, so manual "Share → Add to
  Home Screen" instructions are shown instead. This step is *required* on
  iPhone before notifications can work at all.

The invitation only appears after three cards have been read, and dismissal is
permanent. Saved cards are written to IndexedDB as full records, so they open
with no connection; the service worker additionally caches the shell and API
reads, but never `/api/v1/me/*` — one person's saves must not be served to
another on a shared device.

### Notifications

```bash
docker compose run --rm api python -m app.cli vapid   # prints a keypair
# paste both into .env, then:
docker compose restart api
```

At most one notification per day, enforced server-side rather than by good
intentions. There are no streak-loss warnings and no manufactured urgency —
every notification names a specific thing to learn so it can be judged before
being opened. The composer tries, in order: continue a thread you started,
somewhere you have never explored, then today's pick.

---

## Telegram

Curio has two faces inside Telegram, over one corpus and one reader profile:

- **The chat bot** — `/random`, `/search`, and plain questions answered in the
  chat. A card arrives as its question and one-sentence answer, and the five
  explanation levels are turned with the `◀ ▶` buttons, in place, so the chat
  keeps one message per card rather than five. `🧠` lists the terms it
  introduces, `⚠️` the misconceptions, `📚` the sources.
- **The Mini App** — the same Next.js frontend in Telegram's webview, opened
  from the menu button beside the message box.

Cards can be read in English or Russian; `/lang` switches, and a Russian
Telegram client gets Russian from the first message. See
[Reading in Russian](#reading-in-russian) below.

They are the same reader. Saving a card from a chat message puts it on the
Saved page, the streak counts either way, and a reader who used the web app
first keeps their history when they open it in Telegram — the browser's
anonymous profile key is handed over on first sign-in and adopted.

### Setting it up

```bash
# 1. @BotFather -> /newbot. Put the token and the @name in .env:
#      TELEGRAM_BOT_TOKEN=...
#      TELEGRAM_BOT_USERNAME=...

# 2. Telegram only talks to https, so localhost needs a tunnel:
cloudflared tunnel --url http://localhost:3001

# 3. Put that https URL in .env, twice — the frontend proxies /api through to
#    the API, so one tunnel serves both the Mini App and the webhook:
#      TELEGRAM_WEBAPP_URL=https://<name>.trycloudflare.com
#      TELEGRAM_PUBLIC_URL=https://<name>.trycloudflare.com

docker compose up -d api web
docker compose run --rm api python -m app.cli telegram setup
```

`telegram setup` registers the webhook, the command list, the description, and
the Mini App menu button, and generates `TELEGRAM_WEBHOOK_SECRET` if you left
it empty — paste it into `.env` and restart the API. `telegram info` prints
Telegram's own view of the webhook, including the last delivery error, which is
where to look first when nothing happens. `telegram delete` unregisters it.

One thing is not scriptable: **inline mode**. To type `@yourbot wifi` in any
chat and share a card, send BotFather `/setinline`.

A quick tunnel gets a new URL every restart. When it changes, update both URLs
in `.env`, restart, and run `telegram setup` again.

### Reading in Russian

The corpus is written in English. Rather than maintaining a parallel one, cards
are translated on demand and the result is kept — so the first reader of a card
in Russian waits about two seconds, and everyone after them waits none.

`/lang` switches between English and Русский. A reader whose Telegram client is
set to Russian is answered in Russian from the first message, without having to
find the setting; `/lang` overrides that permanently once used.

Two layers, deliberately different:

- **The bot's own words** — buttons, commands, headings, error messages — are
  hand-written in `backend/app/telegram/strings.py`. Sending a fixed vocabulary
  through a model on every message would mean paying for it, waiting for it,
  and having the same button worded two different ways on two different days.
- **Card content** — titles, levels, key terms, misconceptions — goes through
  `backend/app/services/translation.py`, which batches, caches, and never fails.

Three properties matter more than translation quality:

| | |
| --- | --- |
| **Batched** | Everything a view needs is one model call. Per-string requests would exhaust a free-tier quota on a single card. |
| **Cached** | Keyed on a hash of the source text, in the `translations` table. The same sentence in two cards costs one translation; rewriting one field does not invalidate the rest of the card. |
| **Never fatal** | If every provider is out of quota, the reader gets the English back. A card in the wrong language beats an error message, and it matches what the platform already promises about AI being additive. |

Translation is per *view*, not per card. A card holds around fifty translatable
strings, and putting all of them through a model before showing a preview would
make `/random` take ten seconds. Each view asks for the handful it needs;
because the cache is keyed on source text, the title is translated once and is
a cache hit in every view after the first.

Searching in Russian works because the query is translated to English before it
reaches the index — Meilisearch and the embeddings are both built from English
cards, so an untranslated Russian question matches nothing on words and only
vaguely on meaning. The reply says which English query was actually run, since
otherwise the results look unrelated to what was typed. Queries are **not**
cached: they are near-unique, and a table of everything anyone ever typed is
not something this platform should accumulate.

Source titles are never translated. A citation you cannot look up is worse than
one in the wrong language.

Adding a language is a dictionary in `strings.py` and an entry in `LANGUAGES`;
nothing else is language-specific.

### How it hangs together

| Piece | Where |
| --- | --- |
| Bot API client | `backend/app/services/telegram.py` |
| Update handlers | `backend/app/telegram/handlers.py` |
| Card → Telegram HTML | `backend/app/telegram/render.py` |
| Inline keyboards, callback vocabulary | `backend/app/telegram/keyboards.py` |
| Mini App signature check | `backend/app/telegram/initdata.py` |
| Translation engine and cache | `backend/app/services/translation.py` |
| Bot's own strings, per language | `backend/app/telegram/strings.py` |
| Card localized for one view | `backend/app/telegram/localize.py` |
| Webhook + sign-in routes | `backend/app/api/v1/telegram.py` |
| Webview lifecycle, theme, back button | `frontend/src/components/telegram/telegram-bridge.tsx` |

Two things are load-bearing for security. The webhook URL is public, so every
delivery must carry the secret token Telegram was given in `setWebhook`, and
the route refuses updates outright if the secret is unset rather than falling
open. And `initData` reaches the server through the browser, so it is
attacker-controlled until its HMAC is verified against the bot token — that
check is the only thing separating "this is Telegram user 12345" from anyone
willing to type that number into a request.

The webhook always answers `200`, including for updates it cannot handle: a
non-2xx is redelivered with backoff, so a handler bug would otherwise become
the same broken reply sent forever.

---

## Personalisation without an echo chamber

Interest weights decay over time, so a week on aviation does not define you
permanently. More importantly, `serendipity` is a **floor**, not a target: a
fixed share of every recommendation set is drawn from categories you have not
engaged with, and it cannot reach zero. Readers can raise it on `/you`; they
cannot switch it off.

There is no account and no password. The browser generates a random key, sent
as `X-Curio-Profile`. Copying that key to another device is how syncing works.

---

## Operations

```bash
# Load or reload the curated corpus
docker compose run --rm api python -m app.cli seed [--force]

# Collect questions from public forums (no AI key needed for this half)
docker compose run --rm api python -m app.cli ingest --discover-only

# Full run: collect, triage, synthesise (needs an AI key)
docker compose run --rm api python -m app.cli ingest

# Write one card on demand
docker compose run --rm api python -m app.cli synthesize "Why is the sky blue?"

# Rebuild the search index
docker compose run --rm api python -m app.cli reindex

# Register the bot's webhook, commands and Mini App button
docker compose run --rm api python -m app.cli telegram [setup|info|delete]
```

Scheduled ingestion is off by default. Set `INGESTION_ENABLED=true` to poll
public sources every `INGESTION_INTERVAL_MINUTES`. A run writes at most
`INGESTION_MAX_NEW_CARDS` cards — forty mediocre cards are worse for the
platform than three good ones.

The `/api/v1/admin/*` endpoints do the same things over HTTP and are
**unauthenticated by design in development**. Put them behind ingress auth or
remove the router before exposing the API publicly.

---

## Development without Docker

```bash
# Backend (needs Postgres with pgvector, and Meilisearch, running somewhere)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

The frontend proxies `/api/*` to `API_URL` (see `next.config.ts`), which keeps
the API same-origin in the browser — required for the service worker to cache
API responses and for push subscription to work without a CORS exception.

---

## Deployment

Two supported shapes. Both give the Telegram bot a stable https hostname,
which is the thing a `trycloudflare.com` quick tunnel cannot do — it dies with
the process and comes back on a new URL, taking the webhook with it.

| | Managed split | [Single VM](docs/DEPLOY-ORACLE.md) |
| --- | --- | --- |
| Hosts | Vercel + Railway | one Oracle Always Free machine |
| Cost | ~$5/month | free — Tailscale Funnel needs no domain |
| You maintain | nothing | the OS, disk and backups |
| Files | `.env.production.example` | `docker-compose.prod.yml` |

The managed split is below. For the free path — the whole stack on one box
behind a Cloudflare Tunnel, with no inbound port open — see
**[docs/DEPLOY-ORACLE.md](docs/DEPLOY-ORACLE.md)**.

### The managed split

Four services across two hosts: Vercel runs the frontend, Railway runs
the API, Postgres and Meilisearch. Copy `.env.production.example` — it lists
every variable each side needs and why.

### 1. Railway — Postgres

New project → **Deploy Postgres**. Use a template with **pgvector** available
(Railway's Postgres images ship the extension; the app runs
`CREATE EXTENSION vector` itself on first boot, so nothing else is needed).

### 2. Railway — Meilisearch

Add a service from the Docker image `getmeili/meilisearch:v1.12`, give it a
volume mounted at `/meili_data`, and set `MEILI_MASTER_KEY` to a long random
string. It needs no public domain — the API reaches it over the private
network at `http://meilisearch.railway.internal:7700`.

### 3. Railway — the API

Add a service from this repo with the root directory set to `backend`; the
Dockerfile is used as-is. Set the variables from `.env.production.example`,
referencing the other services rather than pasting literals:

```bash
DATABASE_URL=${{Postgres.DATABASE_URL}}
MEILI_URL=http://meilisearch.railway.internal:7700
MEILI_MASTER_KEY=${{Meilisearch.MEILI_MASTER_KEY}}
AUTO_SEED=true
ADMIN_API_ENABLED=false
```

Then generate a public domain for it. Two things are already handled: the
container binds `$PORT` rather than a fixed 8000, and a `postgresql://` URL is
rewritten to the async driver SQLAlchemy requires.

On first boot the API creates the extensions and tables, seeds all fifty-nine
curated cards, builds the graph and indexes into Meilisearch — the same
sequence as a local `docker compose up`. Watch the logs; it takes a minute.

### 4. Vercel — the frontend

Import the repo with the root directory set to `frontend`. Set `API_URL` to
the Railway public URL (no trailing slash) and `NEXT_PUBLIC_VAPID_PUBLIC_KEY`
if you want push.

`API_URL` is the load-bearing one. Server components call the API directly,
while the browser goes through the rewrite in `next.config.ts` so that `/api/*`
stays same-origin — which is what lets the service worker cache API responses
and lets push subscription work without a CORS exception.

### Afterwards

* **Admin endpoints stay off.** `ADMIN_API_ENABLED=false` removes the router
  entirely. Use `railway run python -m app.cli <command>` for seeding,
  ingestion and reindexing — same commands, authenticated by your Railway
  session rather than by nothing at all.
* **Schema changes.** `init_models()` creates tables on boot but never alters
  them. Once there is data worth keeping, add Alembic and set `AUTO_SEED=false`.
* **Meilisearch is rebuildable.** Its volume can be wiped without data loss;
  the API reindexes from Postgres on every boot.
