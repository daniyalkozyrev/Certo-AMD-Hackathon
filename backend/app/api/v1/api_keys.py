"""API-key management: mint / list / revoke machine credentials.

A key lets an external agent authenticate to `POST /traces` (and the rest of the
API) as its owning user, without embedding a user JWT. Create/list/revoke here
require a normal logged-in session (JWT or an existing key).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.exceptions import NotFoundError
from app.core.security import api_key_display_prefix, generate_api_key, hash_api_key
from app.models.user import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRead

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate, session: SessionDep, user: CurrentUser
) -> ApiKeyCreated:
    raw = generate_api_key()
    key = ApiKey(
        user_id=user.id,
        name=payload.name,
        key_hash=hash_api_key(raw),
        prefix=api_key_display_prefix(raw),
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    # The plaintext key is returned exactly once here and never stored/retrievable.
    return ApiKeyCreated(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        last_used_at=key.last_used_at,
        revoked=key.revoked,
        created_at=key.created_at,
        key=raw,
    )


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(session: SessionDep, user: CurrentUser) -> list[ApiKey]:
    rows = (
        await session.execute(
            select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> None:
    key = await session.get(ApiKey, key_id)
    if key is None or key.user_id != user.id:
        raise NotFoundError("API key not found")
    key.revoked = True
    await session.commit()
