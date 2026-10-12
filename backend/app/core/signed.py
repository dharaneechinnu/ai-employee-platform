"""Short-lived signed tokens for flows that leave the app and come back.

Two uses: the OAuth `state` parameter, which proves a callback belongs
to a sign-in we started, and approval links in notification messages.

Each token carries a `typ` naming its purpose, and verification
demands that exact purpose. An access token has typ "access", so a
state or approval-link token can never be replayed as a session, and
a session token can never be replayed as either of these.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt

from app.config import get_settings

Purpose = Literal["oauth_state", "approval_link"]


class InvalidSignedTokenError(Exception):
    pass


def sign(purpose: Purpose, claims: dict[str, Any], *, expires_at: datetime) -> str:
    settings = get_settings()
    payload = {
        **claims,
        "typ": purpose,
        "iat": datetime.now(UTC),
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def sign_for(purpose: Purpose, claims: dict[str, Any], *, minutes: int) -> str:
    return sign(purpose, claims, expires_at=datetime.now(UTC) + timedelta(minutes=minutes))


def verify(token: str, purpose: Purpose) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidSignedTokenError("This link has expired.") from exc
    except jwt.PyJWTError as exc:
        raise InvalidSignedTokenError("This link is not valid.") from exc
    if payload.get("typ") != purpose:
        raise InvalidSignedTokenError("This link is not valid.")
    return payload
