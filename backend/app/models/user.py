"""User accounts and login codes (email+password with email verification, + Google OAuth)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import GUID, Base, TimestampMixin, UUIDMixin


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "email" (password login) or "google"
    auth_provider: Mapped[str] = mapped_column(String(32), default="email", nullable=False)
    # bcrypt hash of the password (null for Google users / not-yet-set). NEVER plaintext.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Email ownership confirmed via the one-time code before login is allowed.
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class LoginCode(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "login_codes"

    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ApiKey(UUIDMixin, TimestampMixin, Base):
    """A long-lived machine credential so an external agent can POST traces
    without a user JWT. Only the keyed hash is stored; the plaintext key is shown
    to the user exactly once at creation. Acts as its owning user (user-scoped)."""

    __tablename__ = "api_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # HMAC-SHA256 hex digest — unique + indexed so auth is a single lookup.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # Non-secret leading chars (e.g. "certo_sk_ab12cd") shown in the dashboard.
    prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
