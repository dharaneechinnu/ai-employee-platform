"""Auth request and response bodies.

These are the API contract. The generated TypeScript client is derived
from them, so a change here is a change the frontend sees at compile
time.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Long enough to resist guessing, short enough not to push people toward
# writing it down. Length beats composition rules, so there are none.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 200


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class TokenResponse(BaseModel):
    """The refresh token is deliberately absent: it is set as an httpOnly
    cookie so JavaScript cannot read it, which is most of its value."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth scheme name, not a secret
    expires_in: int


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None


class SetupRequest(BaseModel):
    """Setting a password from the link the Platform Admin sent."""

    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    full_name: str | None = Field(default=None, max_length=200)
