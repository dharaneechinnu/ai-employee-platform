"""Identity: users, memberships, invitations, refresh tokens, platform admins.

Two separations matter here and are deliberate:

1. `platform_admins` is its own table, not a role on `users`. A bug in
   role-checking logic can then never escalate a customer to platform
   staff, because they are not in the same table to begin with.

2. `users` has no `org_id`. A person may belong to several companies;
   the link lives in `memberships`. This is why `users` is on the
   tenant-isolation whitelist.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Role(StrEnum):
    """Roles inside one company. Deliberately only two.

    Admin builds the AI Employees; Member uses them. A read-only Viewer
    is a plausible third role later, which is why permissions are
    resolved through a matrix rather than scattered `if role ==` checks.
    """

    ADMIN = "admin"
    MEMBER = "member"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Membership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_memberships_user_org"),
        Index("ix_memberships_org_id", "org_id"),
        Index("ix_memberships_user_id", "user_id"),
    )


class Invitation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An invite link. There is no public registration endpoint, so this
    is the only way a user account comes into existence."""

    __tablename__ = "invitations"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[Role] = mapped_column(String(20), nullable=False)

    # Only the hash is stored. A database leak must not yield usable
    # invite links.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_invitations_org_id", "org_id"),)

    def is_usable(self, now: datetime) -> bool:
        return self.used_at is None and self.expires_at > now


class RefreshToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One issued refresh token.

    `family_id` groups every token descended from a single login. On
    rotation we issue a new row in the same family and revoke the old
    one. If a revoked token is presented again it was stolen, so the
    entire family is revoked and the session is killed.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_refresh_tokens_family_id", "family_id"),
        Index("ix_refresh_tokens_user_id", "user_id"),
    )

    def is_usable(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now


class PlatformAdmin(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Platform staff. Separate table from `users` on purpose.

    2FA is compulsory: this account can create and suspend companies, so
    a password alone is not enough.
    """

    __tablename__ = "platform_admins"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    totp_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformAdminAudit(Base, UUIDPrimaryKeyMixin):
    """Append-only record of every platform-admin action.

    The application is never granted UPDATE or DELETE on this table (see
    the migration). Enforcing that with database grants rather than
    convention means the log survives a compromise of the app itself.
    """

    __tablename__ = "platform_admin_audit"

    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_admins.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
