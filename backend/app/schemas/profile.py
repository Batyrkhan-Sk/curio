"""Reader-facing request/response shapes."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.card import CardSummary


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    display_name: str = "Curious reader"
    interests: dict[str, float] = Field(default_factory=dict)
    preferred_level: int = 1
    serendipity: float = 0.35
    streak_days: int = 0
    longest_streak: int = 0
    last_active_on: date | None = None
    notify_daily: bool = True
    notify_hour_utc: int = 17
    notify_weekly_digest: bool = True


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    preferred_level: int | None = Field(default=None, ge=1, le=5)
    serendipity: float | None = Field(default=None, ge=0.1, le=0.9)
    notify_daily: bool | None = None
    notify_hour_utc: int | None = Field(default=None, ge=0, le=23)
    notify_weekly_digest: bool | None = None


class InteractionIn(BaseModel):
    card_id: uuid.UUID
    kind: str = Field(pattern="^(view|save|unsave|complete|level_reached|asked_again|dismissed)$")
    level: int = Field(default=0, ge=0, le=5)
    seconds: int = Field(default=0, ge=0)


class StatsOut(BaseModel):
    cards_read: int = 0
    cards_saved: int = 0
    cards_completed: int = 0
    concepts_explored: int = 0
    connections_followed: int = 0
    minutes_learning: int = 0
    streak_days: int = 0
    longest_streak: int = 0
    discoveries_this_week: int = 0
    top_categories: list[dict] = Field(default_factory=list)


class SavedOut(BaseModel):
    cards: list[CardSummary] = Field(default_factory=list)


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: PushKeys
    user_agent: str = ""


class ReexplainIn(BaseModel):
    tried: list[str] = Field(default_factory=list)
    last_response: str | None = None
    mode: str | None = None


class ReexplainOut(BaseModel):
    mode: str
    label: str
    body: str
    generated: bool = True
    tried: list[str] = Field(default_factory=list)
