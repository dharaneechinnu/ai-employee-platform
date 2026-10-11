"""Auth request and response bodies.

These are the API contract. The generated TypeScript client is derived
from them, so a change here is a change the frontend sees at compile
time.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.db.models.identity import Role

# Long enough to resist guessing, short enough not to push people toward
# writing it down. Length beats composition rules, so there are none.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 200


class _PasswordMixin(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("password")
    @classmethod
    def _not_entirely_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("password cannot be only whitespace")
        return v


class AcceptInviteRequest(_PasswordMixin):
    """The only way an account is created — there is no public sign-up."""

    token: str = Field(min_length=10, max_length=200)
    full_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class TokenResponse(BaseModel):
    """The refresh token is deliberately absent: it is set as an httpOnly
    cookie so JavaScript cannot read it, which is most of its value."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth scheme name, not a secret
    expires_in: int


class OrgSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    role: Role


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    organizations: list[OrgSummary]


class MemberSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: Role


class InviteRequest(BaseModel):
    email: EmailStr
    role: Role = Role.MEMBER


class InviteResponse(BaseModel):
    """Carries the raw token exactly once, at creation.

    There is no email service, so the admin copies this link and sends it
    themselves. We store only the hash, so this response is the single
    opportunity to see the token — it cannot be retrieved later.
    """

    id: uuid.UUID
    email: EmailStr
    role: Role
    invite_token: str
    expires_at: datetime


class UpdateMemberRoleRequest(BaseModel):
    role: Role
