"""Agents: saved helpers a person designs, by talking.

An agent is a name, instructions, an optional narrower tool list and a
preferred AI. It is only ever configuration: when a chat uses it, the
normal assistant runs with the agent's instructions, so the person's
Permissions, approvals, memory and cost tracking all still apply.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MAX_AGENTS = 30
# A scheduled run does a whole job, not one chat turn, so it gets more
# steps than a chat does. Still bounded: a confused agent must not loop.
DEFAULT_RUN_STEPS = 40
MAX_RUN_STEPS = 80


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
    # True when `tools` was worked out from the instructions (see
    # `app.agent.tool_infer`), so it is worked out again when they change.
    tools_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- running on its own -------------------------------------------
    # {"frequency": "daily"|"weekdays"|"weekly", "time": "23:30",
    #  "days": [0..6] (weekly), "timezone": "Asia/Kolkata"}, or None for
    # an agent that only works when someone chats with it.
    schedule: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "completed", "failed", "needs_attention" (a connection stopped
    # working) or "running".
    last_status: Mapped[str | None] = mapped_column(String(30))
    last_summary: Mapped[str | None] = mapped_column(String(1000))
    # The conversation its runs are written into, so every night's
    # result can be read like any chat.
    run_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=DEFAULT_RUN_STEPS)
    # What the agent may touch inside an app: {"sheet_ids": ["..."]}.
    # Narrower than the connection, never wider.
    scope: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_agents_owner", "owner_id"),
        Index("ix_agents_due", "schedule_enabled", "next_run_at"),
        Index("uq_agents_owner_handle", "owner_id", "handle", unique=True),
    )
