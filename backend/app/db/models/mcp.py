"""MCP tool servers a company has connected.

MCP (Model Context Protocol) is the open standard for "a server that
offers tools". Connect one, and every tool it offers becomes a tool
the company's AI Employees can use, with the same permissions,
approvals and audit trail as a built-in one. No code on our side per
tool: the server describes its own tools.

The tool list is cached here when the server is synced, so the tool
picker and permission screens never wait on, or depend on, the server
being up. The worker calls the server only when a tool actually runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class McpServer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "mcp_servers"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Part of every tool name ("mcp__crm__find_customer"), so it is
    # short, lowercase and fixed once chosen.
    slug: Mapped[str] = mapped_column(String(30), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)

    # The server's access token, if it needs one. Encrypted and
    # write-only, like every other secret here.
    token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    token_last4: Mapped[str | None] = mapped_column(String(8))

    # [{name, title, description, input_schema, effect}], as of the last sync.
    tools: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="untested")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_mcp_server_org_slug"),
        Index("ix_mcp_servers_org", "org_id"),
    )
