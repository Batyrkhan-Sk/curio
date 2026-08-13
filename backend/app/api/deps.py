"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import Profile
from app.services.personalization import get_or_create_profile

DbSession = Annotated[AsyncSession, Depends(get_session)]

PROFILE_HEADER = "X-Curio-Profile"


async def current_profile(
    response: Response,
    session: DbSession,
    x_curio_profile: Annotated[str | None, Header(alias=PROFILE_HEADER)] = None,
) -> Profile:
    """Resolve the anonymous reader, creating one on first contact.

    The generated key is echoed back in the same header so the client can store
    it. No cookie, no account, no password — the key *is* the identity, and
    copying it to another device is how syncing works.
    """
    profile = await get_or_create_profile(session, x_curio_profile)
    await session.commit()
    response.headers[PROFILE_HEADER] = profile.key
    return profile


CurrentProfile = Annotated[Profile, Depends(current_profile)]


async def optional_profile(
    session: DbSession,
    x_curio_profile: Annotated[str | None, Header(alias=PROFILE_HEADER)] = None,
) -> Profile | None:
    """For endpoints that personalise when possible but never require it."""
    if not x_curio_profile:
        return None
    from sqlalchemy import select

    return await session.scalar(select(Profile).where(Profile.key == x_curio_profile))


OptionalProfile = Annotated[Profile | None, Depends(optional_profile)]


def not_found(what: str = "Card") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")
