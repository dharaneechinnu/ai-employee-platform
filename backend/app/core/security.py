"""Password hashing and JWT handling.

Design notes:

- Argon2id for passwords. It is memory-hard, so a stolen database cannot
  be cracked cheaply on GPUs the way bcrypt-at-low-cost or any plain hash
  can be.
- Short-lived access tokens (15 min) carried in the Authorization header,
  long-lived refresh tokens in an httpOnly cookie. A stolen access token
  expires quickly; a refresh token is not reachable from JavaScript.
- Refresh tokens rotate, and rotation is tracked by *family*. Reusing an
  already-rotated token means it was stolen, so the whole family is
  revoked. See `app.services.auth_service`.
- Only the hash of a refresh token is stored, never the token itself, so
  a database leak does not hand over working sessions.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings

_hasher = PasswordHasher()

TokenType = Literal["access", "platform_access"]


# ----------------------------------------------------------------- passwords


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return True


def needs_rehash(hashed: str) -> bool:
    """True when the stored hash used weaker parameters than we now use."""
    return _hasher.check_needs_rehash(hashed)


# ----------------------------------------------------------------- access tokens


def create_access_token(
    *,
    subject: uuid.UUID,
    token_type: TokenType = "access",  # noqa: S107 - a token kind, not a secret
    extra_claims: dict[str, Any] | None = None,
    ttl: timedelta | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "iat": now,
        "exp": now + (ttl or timedelta(minutes=settings.access_token_minutes)),
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, *, expected_type: TokenType = "access") -> dict[str, Any]:
    """Decode and validate. Raises `jwt.PyJWTError` on any problem."""
    settings = get_settings()
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "typ"]},
    )
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    return payload


# ----------------------------------------------------------------- refresh tokens


def generate_refresh_token() -> str:
    """A long random string. Opaque — it carries no claims of its own."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """SHA-256 for refresh tokens and setup-link tokens.

    Deliberately not Argon2: these are high-entropy random strings, not
    user-chosen passwords, so there is nothing to brute-force and we do
    not want a slow hash on the hot refresh path.
    """
    return hashlib.sha256(token.encode()).hexdigest()
