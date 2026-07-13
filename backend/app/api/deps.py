"""Shared API dependencies: DB session, pagination, (placeholder) auth."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import CertoError
from app.core.security import API_KEY_PREFIX, decode_access_token, hash_api_key
from app.models.user import ApiKey, User


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(db_session)]


@dataclass
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PaginationDep = Annotated[Pagination, Depends(pagination)]


# ── Authentication ───────────────────────────────────────────
class AuthError(CertoError):
    """Authentication failed."""

    status_code = 401
    code = "unauthorized"


_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AuthError("Not authenticated")
    token = credentials.credentials
    # A machine API key and a user JWT arrive in the SAME Authorization header;
    # the key's distinctive prefix tells them apart (external agents send keys).
    if token.startswith(API_KEY_PREFIX):
        return await _user_from_api_key(session, token)

    try:
        payload = decode_access_token(token)
    except Exception as exc:  # invalid / expired token
        raise AuthError("Invalid or expired token") from exc

    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise AuthError("User not found")
    return user


async def _user_from_api_key(session: AsyncSession, token: str) -> User:
    """Resolve a machine API key to its owning user (single indexed lookup)."""
    key = (
        await session.execute(
            select(ApiKey).where(
                ApiKey.key_hash == hash_api_key(token), ApiKey.revoked.is_(False)
            )
        )
    ).scalar_one_or_none()
    if key is None:
        raise AuthError("Invalid or revoked API key")
    user = await session.get(User, key.user_id)
    if user is None:
        raise AuthError("User not found")
    # Best-effort telemetry: persists on endpoints that commit (e.g. POST /traces).
    key.last_used_at = datetime.now(UTC)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
