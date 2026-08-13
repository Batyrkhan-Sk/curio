"""Application settings.

Everything is environment driven so the same image runs locally, in Docker,
and on Railway/Fly/DigitalOcean without code changes.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Curio"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)

    # --- Database ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://curio:curio@localhost:5433/curio",
        alias="DATABASE_URL",
    )

    # --- Search -----------------------------------------------------------
    meili_url: str = Field(default="http://localhost:7700", alias="MEILI_URL")
    meili_master_key: str = Field(default="curio_dev_master_key", alias="MEILI_MASTER_KEY")
    meili_cards_index: str = "cards"

    # --- AI ---------------------------------------------------------------
    # An empty key disables every LLM-backed feature. The platform degrades to
    # curated content, keyword search, and the pre-computed graph.
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.6-flash", alias="GEMINI_MODEL")
    # Free-tier request quotas are counted *per model*, so rotating through
    # several multiplies the daily allowance. Ordered best-first: when one is
    # exhausted the client falls to the next rather than stopping.
    gemini_model_pool: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash-001",
            "gemini-2.0-flash-lite",
        ],
        alias="GEMINI_MODEL_POOL",
    )
    gemini_embedding_model: str = Field(
        default="gemini-embedding-001", alias="GEMINI_EMBEDDING_MODEL"
    )
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        alias="GEMINI_BASE_URL",
    )
    # --- Groq — fast OpenAI-compatible inference, the main fallback --------
    # Note the spelling: Groq (api.groq.com) is an inference provider running
    # open models; Grok is xAI's model, configured separately below as XAI_*.
    # Mixing the two up puts a gsk_ key against api.x.ai and gets it rejected.
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1", alias="GROQ_BASE_URL"
    )
    # Groq's free tier caps a whole request — prompt plus completion — at 8000
    # tokens per minute, and `max_tokens` counts toward that estimate. Asking
    # for Gemini's 32k ceiling gets a 413 before the model sees the prompt.
    groq_max_output_tokens: int = Field(default=6000, alias="GROQ_MAX_OUTPUT_TOKENS")
    groq_model_pool: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "openai/gpt-oss-120b",
            "llama-3.3-70b-versatile",
            "qwen/qwen3.6-27b",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant",
        ],
        alias="GROQ_MODEL_POOL",
    )

    # --- xAI (Grok) --------------------------------------------------------
    xai_api_key: str = Field(default="", alias="XAI_API_KEY")
    xai_model: str = Field(default="grok-4-fast", alias="XAI_MODEL")
    xai_base_url: str = Field(default="https://api.x.ai/v1", alias="XAI_BASE_URL")

    # Tried in order. Gemini leads because it is the only one with embeddings.
    llm_provider_order: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["gemini", "groq", "xai"], alias="LLM_PROVIDER_ORDER"
    )

    embedding_dim: int = Field(default=768, alias="EMBEDDING_DIM")
    llm_timeout_seconds: float = Field(default=180.0, alias="LLM_TIMEOUT_SECONDS")

    # Reasoning models (Gemini 3.x, and others) spend output tokens on internal
    # thinking before writing a word, and that spend counts against
    # maxOutputTokens. A full knowledge card needs ~4k tokens of actual JSON, so
    # the ceiling has to leave room for both or the response is truncated
    # mid-string and fails to parse.
    llm_max_output_tokens: int = Field(default=32768, alias="LLM_MAX_OUTPUT_TOKENS")
    # "low" | "high" | "" to leave the model's default alone. Lower thinking
    # means more of the budget reaches the page, and for structured extraction
    # it costs very little quality.
    gemini_thinking_level: str = Field(default="low", alias="GEMINI_THINKING_LEVEL")

    # --- Ingestion --------------------------------------------------------
    ingestion_enabled: bool = Field(default=False, alias="INGESTION_ENABLED")
    ingestion_interval_minutes: int = Field(default=180, alias="INGESTION_INTERVAL_MINUTES")
    ingestion_max_new_cards_per_run: int = Field(default=5, alias="INGESTION_MAX_NEW_CARDS")
    reddit_user_agent: str = Field(
        default="curio/0.1 (collective-curiosity)", alias="REDDIT_USER_AGENT"
    )

    # Threads needs a real browser to render, so its collector talks to the
    # worker in backend/workers/threads rather than fetching anything itself.
    # Off by default: with no worker running the collector is a no-op, and
    # there is no point paying for the round trip to discover that.
    threads_enabled: bool = Field(default=False, alias="THREADS_ENABLED")
    threads_worker_url: str = Field(default="", alias="THREADS_WORKER_URL")
    threads_tags: list[str] = Field(default_factory=list, alias="THREADS_TAGS")
    """Overrides the curiosity tags in the collector. Comma-separated in env."""
    # Optional. With a script-type app's credentials the collector uses the
    # authenticated API — 100 requests a minute, scores and comment counts
    # included. Without them it falls back to the public Atom feed, which is
    # throttled to roughly one subreddit per attempt and carries no scores.
    reddit_client_id: str = Field(default="", alias="REDDIT_CLIENT_ID")
    reddit_client_secret: str = Field(default="", alias="REDDIT_CLIENT_SECRET")

    @property
    def reddit_oauth_enabled(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret)

    # --- Content ----------------------------------------------------------
    auto_seed: bool = Field(default=True, alias="AUTO_SEED")

    # Set false whenever the API is reachable beyond localhost. The CLI does
    # everything these endpoints do, so turning them off costs nothing.
    admin_api_enabled: bool = Field(default=True, alias="ADMIN_API_ENABLED")

    # --- Telegram ---------------------------------------------------------
    # The token BotFather hands out. Empty disables the webhook route, the bot
    # commands, and Mini App authentication — the web app is unaffected.
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    # Sent by Telegram as X-Telegram-Bot-Api-Secret-Token on every webhook call.
    # The webhook URL is public and guessable, so without this anyone could post
    # forged updates. Generated by `python -m app.cli telegram setup`.
    telegram_webhook_secret: str = Field(default="", alias="TELEGRAM_WEBHOOK_SECRET")
    # Public HTTPS origin of the frontend, e.g. https://curio.trycloudflare.com.
    # Telegram refuses to open a Mini App over http or from an IP address, so in
    # development this is a tunnel rather than localhost.
    telegram_webapp_url: str = Field(default="", alias="TELEGRAM_WEBAPP_URL")
    # Public HTTPS origin of *this* API, which is where Telegram posts updates.
    # Usually the same tunnel as above, since the frontend proxies /api.
    telegram_public_url: str = Field(default="", alias="TELEGRAM_PUBLIC_URL")
    telegram_bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def telegram_webapp_ready(self) -> bool:
        """Whether a Mini App button can be offered at all.

        Telegram silently drops a `web_app` button whose URL is not HTTPS, so
        the keyboards check this and fall back to a plain link rather than
        rendering a button that does nothing when tapped.
        """
        return self.telegram_webapp_url.startswith("https://")

    # --- Web push ---------------------------------------------------------
    vapid_public_key: str = Field(default="", alias="VAPID_PUBLIC_KEY")
    vapid_private_key: str = Field(default="", alias="VAPID_PRIVATE_KEY")
    vapid_subject: str = Field(default="mailto:curiosity@example.com", alias="VAPID_SUBJECT")

    # --- HTTP -------------------------------------------------------------
    # NoDecode stops pydantic-settings from trying to JSON-parse the env value
    # before the validator below gets to split it on commas.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"], alias="CORS_ORIGINS"
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _async_driver(cls, value: object) -> object:
        """Accept the URL managed hosts actually hand out.

        Railway, Fly, Render and Heroku all publish `postgresql://...`, and
        some still publish the legacy `postgres://`. SQLAlchemy needs the async
        driver named explicitly, and the failure otherwise is an import error
        about psycopg2 that says nothing about the real cause.
        """
        if isinstance(value, str):
            for prefix in ("postgresql://", "postgres://"):
                if value.startswith(prefix):
                    return "postgresql+asyncpg://" + value[len(prefix) :]
        return value

    @field_validator(
        "cors_origins",
        "llm_provider_order",
        "gemini_model_pool",
        "groq_model_pool",
        "threads_tags",
        mode="before",
    )
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _restore_empty_pools(self) -> "Settings":
        """Docker Compose writes `VAR=` for an unset variable, which splits to
        an empty list and would silently disable model rotation. Treat an empty
        pool as "not configured" and restore the default.

        The default rather than the single preferred model: an unset variable
        should behave exactly as if Compose had never mentioned it, and
        rotation is the whole reason the pool exists. Falling back to one model
        meant that forwarding the variable at all — which is the only way to
        let anyone set it — quietly cost every deployment its rotation."""
        if not self.gemini_model_pool:
            self.gemini_model_pool = self.model_fields["gemini_model_pool"].get_default(
                call_default_factory=True
            )
        if not self.groq_model_pool:
            self.groq_model_pool = self.model_fields["groq_model_pool"].get_default(
                call_default_factory=True
            )
        if not self.llm_provider_order:
            self.llm_provider_order = ["gemini", "groq", "xai"]
        return self

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key or self.groq_api_key or self.xai_api_key)

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
