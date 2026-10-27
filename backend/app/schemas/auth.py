"""Auth request and response bodies.

These are the API contract. The generated TypeScript client is derived
from them, so a change here is a change the frontend sees at compile
time.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.usernames import USERNAME_MESSAGE, USERNAME_PATTERN, is_valid_username

# Long enough to resist guessing, short enough not to push people toward
# writing it down. Length beats composition rules, so there are none.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 200


class LoginRequest(BaseModel):
    """Sign in with an email or a username. `email` is the older body
    shape and still works."""

    identifier: str | None = Field(default=None, min_length=1, max_length=320)
    email: EmailStr | None = None
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)

    @model_validator(mode="after")
    def _need_one(self) -> LoginRequest:
        if not self.identifier and not self.email:
            raise ValueError("Enter your email or username.")
        return self

    @property
    def who(self) -> str:
        return (self.identifier or str(self.email)).strip()


class RegisterRequest(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    email: EmailStr
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    full_name: str | None = Field(default=None, max_length=200)

    @field_validator("username", mode="before")
    @classmethod
    def _username_message(cls, value: object) -> object:
        if isinstance(value, str) and not is_valid_username(value.strip()):
            raise ValueError(USERNAME_MESSAGE)
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def _password_long_enough(cls, value: str) -> str:
        if len(value) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Use at least {MIN_PASSWORD_LENGTH} characters for your password.")
        return value


class UsernameAvailableResponse(BaseModel):
    available: bool


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
    username: str
    full_name: str | None


class SetupRequest(BaseModel):
    """Setting a password from the link the Platform Admin sent."""

    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    full_name: str | None = Field(default=None, max_length=200)
