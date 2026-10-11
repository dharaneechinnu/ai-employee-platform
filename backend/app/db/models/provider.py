"""AI provider configuration: the menu, and each company's own keys.

Two layers:

- `supported_providers` is the menu the Platform Admin curates.
- `provider_configs` holds the keys. `org_id` set means that company's
  own key (BYOK, the normal case); `org_id` NULL is reserved for an
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


class ProviderKind(StrEnum):
    LLM = "llm"
    EMBEDDING = "embedding"


class ConnectionStatus(StrEnum):
    UNTESTED = "untested"
    WORKING = "working"
    FAILED = "failed"


class SupportedProvider(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The menu. Platform-wide, so no org_id."""

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


class ProviderConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One company's key for one provider.

    The key is stored encrypted and is never returned by any endpoint,
    to anyone - not the company that set it, and not the Platform
    Admin. `key_last4` exists so the UI can show which key is in place
    without the value ever leaving the database.
    """

    __tablename__ = "provider_configs"

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    provider_key: Mapped[str] = mapped_column(String(50), nullable=False)
    api_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_last4: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[ConnectionStatus] = mapped_column(
        StrEnumType(ConnectionStatus, 20), nullable=False, default=ConnectionStatus.UNTESTED
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint("org_id", "provider_key", name="uq_provider_config_org_provider"),
        Index("ix_provider_configs_org_id", "org_id"),
    )
