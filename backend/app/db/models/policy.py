"""Permission policy, approvals, connections and run checkpoints.

The policy model in one line: the Platform Admin sets the **default**
for each action; a person may override it in either direction, looser
or stricter. Only the catastrophic blocklist is fixed.

That split is deliberate. It is their repo, their email and their data,
so a person who understands their own risk should be able to say "we
trust this, stop asking". The blocklist stays because a person who
sets "delete repository" to automatic and loses a repository contacts
us, not themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, StrEnumType, TimestampMixin, UUIDPrimaryKeyMixin


class PolicySetting(StrEnum):
    AUTO = "auto"  # just do it
    ASK = "ask"  # pause and wait for a human
    BLOCKED = "blocked"  # never, even with approval


class PolicyScope(StrEnum):
    PACK = "pack"  # every tool in a pack with a given side effect
    TOOL = "tool"  # one named tool; beats a pack rule


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PolicyDefault(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Platform-wide starting values. No owner_id: this is the menu."""

    __tablename__ = "policy_defaults"

    scope: Mapped[PolicyScope] = mapped_column(StrEnumType(PolicyScope, 20), nullable=False)
    scope_value: Mapped[str] = mapped_column(String(100), nullable=False)
    side_effect: Mapped[str | None] = mapped_column(String(20))
    setting: Mapped[PolicySetting] = mapped_column(StrEnumType(PolicySetting, 20), nullable=False)

    __table_args__ = (
        UniqueConstraint("scope", "scope_value", "side_effect", name="uq_policy_default"),
    )


class Policy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One person's override of a default."""

    __tablename__ = "policies"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[PolicyScope] = mapped_column(StrEnumType(PolicyScope, 20), nullable=False)
    scope_value: Mapped[str] = mapped_column(String(100), nullable=False)
    side_effect: Mapped[str | None] = mapped_column(String(20))
    setting: Mapped[PolicySetting] = mapped_column(StrEnumType(PolicySetting, 20), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "scope", "scope_value", "side_effect", name="uq_policy_org"),
        Index("ix_policies_owner", "owner_id"),
    )


class Approval(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A paused action waiting on a human.

    `proposed` holds the full action, not a summary. An approval screen
    that says "the AI wants to send an email" without the body is
    theatre: you cannot meaningfully approve what you cannot read.
    """

    __tablename__ = "approvals"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    side_effect: Mapped[str] = mapped_column(String(20), nullable=False)
    proposed: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    status: Mapped[ApprovalStatus] = mapped_column(
        StrEnumType(ApprovalStatus, 20), nullable=False, default=ApprovalStatus.PENDING
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Without an expiry, forgotten approvals accumulate for ever and
    # hold half-finished runs open. Better to fail clearly and let the
    # user retry.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_approvals_org_status", "owner_id", "status"),
        Index("ix_approvals_expiry", "status", "expires_at"),
    )


class RunCheckpoint(Base, TimestampMixin):
    """The saved conversation of a paused run.

    A run may wait hours for a human, and the worker cannot sit and
    wait: it must take other jobs. So the state is written here and
    reloaded when the approval arrives.

    Phase 7 replaces this with LangGraph's checkpointer, which also
    handles pausing inside a branch or with parallel steps in flight.
    This handles the single-path case, which is the one phase 5 needs.
    """

    __tablename__ = "run_checkpoints"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pending_tool_call: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ConnectionKind(StrEnum):
    GITHUB = "github"
    EMAIL = "email"
    DATABASE = "database"
    REST = "rest"
    # One-click OAuth connections. One grant covers several apps:
    # Google is Gmail, Calendar and Drive; Microsoft is Outlook mail,
    # calendar and OneDrive.
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class Connection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One person's link to one outside app.

    Same handling as provider keys: encrypted, write-only, never
    returned by any endpoint, and never placed in the model's context.
    """

    __tablename__ = "connections"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ConnectionKind] = mapped_column(StrEnumType(ConnectionKind, 30), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    credential_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    credential_last4: Mapped[str] = mapped_column(String(8), nullable=False)
    # Non-secret settings: allowed domains, the database host, and so on.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="untested")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("owner_id", "kind", "label", name="uq_connection_org_kind_label"),
        Index("ix_connections_owner", "owner_id"),
    )
