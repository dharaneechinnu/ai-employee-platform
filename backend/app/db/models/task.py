"""Tasks, runs and the event log.

Three shapes worth noting:

- `tasks` and `runs` are separate. One task retried three times is one
  intent and three attempts; merging them would lose that.

- `run_events` is append-only and ordered by `seq`. That single
  property gives live streaming, reconnect-with-replay, debugging,
  audit and step-by-step replay — none of them implemented separately.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, StrEnumType, TimestampMixin, UUIDPrimaryKeyMixin


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"  # used from phase 5
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)


class RunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    THINKING = "thinking"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PROVIDER_ERROR = "provider_error"
    RUN_FINISHED = "run_finished"
    RUN_STOPPED = "run_stopped"


class Task(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tasks"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Every task is one turn of a conversation with the person's own
    # assistant. There is no other kind of task.
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )

    title: Mapped[str | None] = mapped_column(String(200))
    input: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        StrEnumType(TaskStatus, 30), nullable=False, default=TaskStatus.QUEUED
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Set by the cancel endpoint; the loop checks it between steps.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Set when an agent's schedule (or its Run now button) started this
    # task. Nobody is watching such a run, so it cannot wait for approval.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL")
    )
    # Who started it: "chat" (the person wrote a message), "schedule" or
    # "manual" (the Run now button). The run copies it when it begins.
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")

    __table_args__ = (
        Index("ix_tasks_owner_status_created", "owner_id", "status", "created_at"),
        Index("ix_tasks_conversation", "conversation_id"),
    )


class Run(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One attempt at a task."""

    __tablename__ = "runs"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Copied from the task so the history list filters and sorts on one
    # table. SET NULL: removing an agent keeps its runs readable.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL")
    )
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")
    status: Mapped[RunStatus] = mapped_column(
        StrEnumType(RunStatus, 30), nullable=False, default=RunStatus.RUNNING
    )

    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Estimated: with BYOK we never see the provider's actual invoice,
    # so this must always be presented as an estimate.
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))

    output: Mapped[str | None] = mapped_column(Text)
    stop_cause: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(2000))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Proof the worker is still alive. Phase 8's reaper requeues runs
    # whose heartbeat has gone stale.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (
        Index("ix_runs_task", "task_id"),
        Index("ix_runs_owner_status", "owner_id", "status"),
        # The history list: one person's runs, newest first, optionally
        # for one agent.
        Index("ix_runs_owner_created", "owner_id", "created_at"),
        Index("ix_runs_owner_agent_created", "owner_id", "agent_id", "created_at"),
    )


class RunEvent(Base):
    """Append-only. Never updated, never deleted.

    `seq` is per-run and gap-free, which is what lets a reconnecting
    client say "I have up to 12" and receive exactly 13 onward.
    """

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),
        Index("ix_run_events_run_seq", "run_id", "seq"),
    )


class SchedulerEvent(Base):
    """What the scheduler did for an agent before (or instead of) a run.

    A run's own events need a run, and "due" and "connections checked"
    happen before one exists. They live here, and the account's live
    stream (see `app.services.live_feed`) merges the two logs so the tree
    can show the whole story of a scheduled start. Append-only.
    """

    __tablename__ = "scheduler_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    # Set once the run's task exists ("started").
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL")
    )
    # agent_due, connections_checked, agent_started or agent_skipped.
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_scheduler_events_owner_id", "owner_id", "id"),)


class LLMCall(Base):
    """One model call. The basis of cost reporting."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_llm_calls_owner_created", "owner_id", "created_at"),)


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    side_effect: Mapped[str] = mapped_column(String(20), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(50))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_tool_invocations_run", "run_id"),)
