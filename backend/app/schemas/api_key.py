"""API-key schemas — machine credentials for external agents (SDK / POST /traces)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Human label, e.g. 'prod agent'.")


class ApiKeyRead(ORMModel):
    id: uuid.UUID
    name: str
    prefix: str  # non-secret leading chars, e.g. "certo_sk_ab12cd"
    last_used_at: datetime | None
    revoked: bool
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """Returned ONCE on creation — carries the plaintext key. Never retrievable again."""

    key: str
