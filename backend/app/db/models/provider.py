"""AI provider configuration: the menu, and each company's own keys.

Two layers:

- `supported_providers` is the menu the Platform Admin curates.
- `provider_configs` holds the keys. `owner_id` set means that company's
  own key (BYOK, the normal case); `owner_id` NULL is reserved for an
  optional platform trial key later. Designing for both now costs a
  nullable column and means a trial is a feature, not a rewrite.

BYOK is what makes a zero-budget platform viable: each company pays
its own model costs, and no customer can inflate another's bill.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, StrEnumType, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.policy import ConnectionKind


class ProviderKind(StrEnum):
    LLM = "llm"
    EMBEDDING = "embedding"


class ConnectionStatus(StrEnum):
    UNTESTED = "untested"
    WORKING = "working"
    FAILED = "failed"


class SupportedProvider(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The menu. Platform-wide, so no owner_id."""

    __tablename__ = "supported_providers"

    key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[ProviderKind] = mapped_column(StrEnumType(ProviderKind, 20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Free tiers commonly allow the provider to train on what is sent.
    # Flagged so the company is warned before they connect, rather than
    # finding out later. For BYOK this is a warning, not a block: it is
    # their key and their choice, but they must be told.
    trains_on_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    default_model: Mapped[str | None] = mapped_column(String(100))
    docs_url: Mapped[str | None] = mapped_column(String(500))

    # How to talk to it, as data, so a new provider is a row rather than
    # a release. `api_format` picks the adapter: "openai" (the format
    # most providers speak), "anthropic" or "gemini". `base_url` is where
    # it lives; `auth_header` is an extra header that carries the key
    # for providers that want one besides `Authorization: Bearer`.
    api_format: Mapped[str] = mapped_column(String(20), nullable=False, default="openai")
    base_url: Mapped[str | None] = mapped_column(String(500))
    auth_header: Mapped[str | None] = mapped_column(String(60))


class ProviderConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One company's key for one provider.

    The key is stored encrypted and is never returned by any endpoint,
    to anyone - not the company that set it, and not the Platform
    Admin. `key_last4` exists so the UI can show which key is in place
    without the value ever leaving the database.
    """

    __tablename__ = "provider_configs"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    provider_key: Mapped[str] = mapped_column(String(50), nullable=False)
    api_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_last4: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[ConnectionStatus] = mapped_column(
        StrEnumType(ConnectionStatus, 20), nullable=False, default=ConnectionStatus.UNTESTED
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))

    # The model this company picked. NULL means the provider's default.
    model: Mapped[str | None] = mapped_column(String(200))
    # Only for the "custom" provider: where the company's own
    # OpenAI-compatible server lives, and what they call it.
    base_url: Mapped[str | None] = mapped_column(String(500))
    label: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint("owner_id", "provider_key", name="uq_provider_config_org_provider"),
        Index("ix_provider_configs_org_id", "owner_id"),
    )


class PlatformOAuthApp(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The one OAuth app per provider that every company signs in through.

    Google and Microsoft issue these per *application*, not per
    customer: one app registration, and each company then grants it
    access to their own mailbox. So this is platform-wide, like
    `supported_providers`, and only a Platform Admin can set it.

    Without a row here (and without the matching environment variables)
    the one-click buttons on a company's Connections page are dead, and
    nothing in the product can turn them on. That was the gap this
    table closes.

    The secret is encrypted under the "platform" scope rather than a
    company's, because it belongs to the platform, and there is no read
    path: the UI only ever sees the last four characters.
    """

    __tablename__ = "platform_oauth_apps"

    provider: Mapped[ConnectionKind] = mapped_column(
        StrEnumType(ConnectionKind, 30), nullable=False, unique=True
    )
    client_id: Mapped[str] = mapped_column(String(300), nullable=False)
    client_secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_last4: Mapped[str] = mapped_column(String(4), nullable=False)

    # Set up but paused: the credentials stay, the buttons go quiet.
    # Deleting is the other option, and it loses the client id too.
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_admins.id", ondelete="SET NULL")
    )


class OrgConnectionAccess(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A Platform Admin's ruling on one company and one connection.

    The platform decides whether a connection exists at all (by
    registering its OAuth app); this decides whether a *particular*
    company may use it. A customer on a plan that excludes email, or
    one who asked for Drive to stay out of reach, is handled here
    rather than by taking the app away from everyone.

    No row means inherit: if the platform has the connection switched
    on, the company may use it. That keeps the common case free of
    rows, and means adding this table changed nothing for anyone
    already connected.

    `owner_id` is here, so the tenancy guard is satisfied honestly — this
    really is per-company data, written by staff rather than by the
    customer.
    """

    __tablename__ = "org_connection_access"
    __table_args__ = (UniqueConstraint("owner_id", "kind", name="uq_org_connection_access"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ConnectionKind] = mapped_column(StrEnumType(ConnectionKind, 30), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Why it was blocked, shown to the company instead of a bare
    # "unavailable" that leaves them with nobody to ask.
    note: Mapped[str | None] = mapped_column(String(300))

    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_admins.id", ondelete="SET NULL")
    )


class PlatformServiceAccess(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Level 1 of service permissions: what the platform allows at all.

    `service` is one part of an app ("google.sheets"); `level` is "read"
    or "edit". No row means allowed, so adding this table changed
    nothing for anyone already connected. A company's own ruling in
    `org_service_access` beats this one, in either direction.
    """

    __tablename__ = "platform_service_access"
    __table_args__ = (UniqueConstraint("service", "level", name="uq_platform_service_access"),)

    service: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_admins.id", ondelete="SET NULL")
    )


class OrgServiceAccess(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A Platform Admin's ruling on one company and one service.

    Same idea as `OrgConnectionAccess`, one level finer: "this company
    may use Drive and Sheets but not Gmail", or "Drive is read only".
    No row means inherit from the platform.
    """

    __tablename__ = "org_service_access"
    __table_args__ = (
        UniqueConstraint("owner_id", "service", "level", name="uq_org_service_access"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    service: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_admins.id", ondelete="SET NULL")
    )


class OrgOAuthApp(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One company's own Google or Microsoft app registration.

    The platform-wide app in `platform_oauth_apps` is the easy path:
    the operator registers once and every company signs in through it.
    This is the other path — a company that would rather its staff
    consent to an app in its own Google Cloud project, with its own
    name on the consent screen and its own quota.

    It also removes the platform admin from the critical path
    entirely: a company can turn one-click on for itself without
    anyone else doing anything first.

    Resolution order is company, then platform, then environment, so
    whichever exists wins in that order and neither path blocks the
    other.
    """

    __tablename__ = "org_oauth_apps"
    __table_args__ = (UniqueConstraint("owner_id", "provider", name="uq_org_oauth_app"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[ConnectionKind] = mapped_column(
        StrEnumType(ConnectionKind, 30), nullable=False
    )
    client_id: Mapped[str] = mapped_column(String(300), nullable=False)
    # Encrypted under this company's own scope, unlike the platform
    # app: it is their credential, and their key should be the one
    # that opens it.
    client_secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_last4: Mapped[str] = mapped_column(String(4), nullable=False)
