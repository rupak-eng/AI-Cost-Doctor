"""Authentication primitives: bcrypt passwords, PyJWT access/refresh tokens.

Deliberately dependency-light: PyJWT + bcrypt directly, no auth framework.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


# ---------------------------------------------------------------------------
# Passwords (bcrypt)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt. Returns the ASCII hash string."""
    pw = password.encode("utf-8")
    if len(pw) > 72:
        raise ValueError("password must be at most 72 bytes")
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time bcrypt verification. Never raises on mismatch."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT access tokens (short-lived)
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(*, user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    now = _utcnow()
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, *, expected_type: str = "access") -> dict:
    """Decode and validate a JWT. Raises jwt.PyJWTError (incl. ExpiredSignatureError) on failure."""
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub", "type"]},
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    # Validate UUID-shaped claims early so callers can trust them.
    uuid.UUID(payload["sub"])
    uuid.UUID(payload["org_id"])
    return payload


# ---------------------------------------------------------------------------
# Refresh tokens (opaque, rotating; only SHA-256 hashes touch the database)
# ---------------------------------------------------------------------------

def new_refresh_token() -> str:
    """Generate an opaque refresh token (never stored; only its hash is)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    return _utcnow() + timedelta(days=settings.refresh_token_expire_days)


# ---------------------------------------------------------------------------
# Project ingest API keys (Phase 3; helpers live here with the other secrets)
# ---------------------------------------------------------------------------

def new_api_key() -> tuple[str, str, str]:
    """Return (plaintext_key, key_hash, key_prefix).

    The plaintext key is shown to the user exactly once; only the SHA-256
    hash is persisted.
    """
    raw = "acd_" + secrets.token_urlsafe(36)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, digest, raw[:8]
