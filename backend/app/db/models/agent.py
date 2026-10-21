"""Agents: saved helpers a person designs, by talking.

An agent is a name, instructions, an optional narrower tool list and a
preferred AI. It is only ever configuration: when a chat uses it, the
normal assistant runs with the agent's instructions, so the person's
Permissions, approvals, memory and cost tracking all still apply.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MAX_AGENTS = 30


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # Short, unique per person, used to @mention the agent.
    handle: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    # "auto" or "provider:model", as on a conversation.
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="auto")
    routing: Mapped[str] = mapped_column(String(20), nullable=False, default="balanced")
    # Tool names this agent may use, or None for everything the person
    # allows. It can only narrow what Permissions already allow.
    tools: Mapped[list[str] | None] = mapped_column(JSONB)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_agents_owner", "owner_id"),
        Index("uq_agents_owner_handle", "owner_id", "handle", unique=True),
    )
