"""Readers, what they have understood, and how to reach them.

There is no password anywhere. A reader is identified by a random key their
browser generates and stores locally, sent as the `X-Curio-Profile` header.
That is enough to personalise and to sync a phone with a desktop (the key can
be copied across), and it keeps the platform from accumulating identities it
has no business holding.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Profile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "profiles"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80), default="Curious reader")

    interests: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    """category slug -> affinity 0..1, decayed over time."""

    known_concepts: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    """concept slug -> estimated familiarity 0..1."""

    preferred_level: Mapped[int] = mapped_column(Integer, default=1)
    serendipity: Mapped[float] = mapped_column(Float, default=0.35)
    """Share of recommendations drawn from outside known interests. The
    anti-echo-chamber dial; never allowed to reach 0."""

    streak_days: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_active_on: Mapped[date | None] = mapped_column(Date)

    notify_daily: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_hour_utc: Mapped[int] = mapped_column(Integer, default=17)
    notify_weekly_digest: Mapped[bool] = mapped_column(Boolean, default=True)

    interactions: Mapped[list["Interaction"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list["PushSubscription"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class Interaction(Base, UUIDMixin):
    __tablename__ = "interactions"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    profile: Mapped[Profile] = relationship(back_populates="interactions")

    card_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(24), index=True)
    """view | save | unsave | complete | level_reached | asked_again | dismissed"""

    level: Mapped[int] = mapped_column(Integer, default=0)
    seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=None, default=datetime.utcnow, index=True
    )


class Collection(Base, UUIDMixin, TimestampMixin):
    """A reader's own shelf, plus the auto-built ones ('Things you finished')."""

    __tablename__ = "collections"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    emoji: Mapped[str] = mapped_column(String(8), default="📚")
    card_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class TelegramLink(Base, UUIDMixin, TimestampMixin):
    """One Telegram account, pointing at the profile it reads as.

    Deliberately a join table rather than a column on `Profile`: the schema is
    bootstrapped with `create_all`, which adds missing *tables* but never
    missing columns, so a new table is the only shape that reaches an existing
    database without a migration.

    The point of the link is that the chat bot and the Mini App are the same
    reader. Saving a card from a chat message puts it on the Saved page, and
    the streak counts either way.
    """

    __tablename__ = "telegram_links"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    """Telegram user id. 64-bit: ids passed 2^32 in 2021."""

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    profile: Mapped[Profile] = relationship()

    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    """Private chat to send unprompted messages to. Same as telegram_id for a
    private chat, but stored separately so it stays correct if that changes."""

    username: Mapped[str] = mapped_column(String(64), default="")
    first_name: Mapped[str] = mapped_column(String(128), default="")
    language_code: Mapped[str] = mapped_column(String(16), default="")
    """What Telegram reports the client's language to be. Only ever a default —
    `locale` is what the reader actually chose."""

    locale: Mapped[str] = mapped_column(String(8), default="")
    """Reading language: "en", "ru", or empty meaning "not chosen yet, follow
    the Telegram client"."""

    mode: Mapped[str] = mapped_column(String(16), default="")
    """Which lens /random and the app open in: "interesting", "useful", or
    empty meaning the default. See services/discovery.py."""

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushSubscription(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "push_subscriptions"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    profile: Mapped[Profile] = relationship(back_populates="subscriptions")

    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str] = mapped_column(Text, default="")
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
