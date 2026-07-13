"""Auth primitives: login-code generation/hashing and JWT access tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"


def generate_code() -> str:
    """A 6-digit numeric login code."""
    return f"{secrets.randbelow(1_000_000):06d}"


# ── Password hashing (bcrypt; plaintext passwords are NEVER stored) ──────────
def hash_password(password: str) -> str:
    """bcrypt hash. (bcrypt truncates at 72 bytes — the schema caps length.)"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_code(code: str) -> str:
    """Keyed hash so plaintext codes are never stored."""
    return hmac.new(settings.secret_key.encode(), code.encode(), hashlib.sha256).hexdigest()


def verify_code(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_code(code), code_hash)


# ── Machine API keys (long-lived creds so external agents can POST traces) ────
# Bearer token an agent presents instead of a user JWT. The distinctive prefix
# lets the auth layer tell an API key from a JWT in the same Authorization header.
API_KEY_PREFIX = "certo_sk_"


def generate_api_key() -> str:
    """A high-entropy, long-lived machine key. Shown to the user exactly once."""
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    """Keyed (deterministic) hash — plaintext keys are NEVER stored, yet the hash
    is directly indexable so verification is a single O(1) lookup, not a scan."""
    return hmac.new(settings.secret_key.encode(), key.encode(), hashlib.sha256).hexdigest()


def api_key_display_prefix(key: str) -> str:
    """The non-secret leading chars shown in the dashboard to identify a key."""
    return key[: len(API_KEY_PREFIX) + 6]


def create_access_token(user_id: uuid.UUID, email: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.access_token_days)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
