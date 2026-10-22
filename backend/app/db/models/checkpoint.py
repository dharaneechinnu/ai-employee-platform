"""LangGraph's saved state for a run that is waiting for a person.

A run may wait hours for an approval, and the worker cannot sit and
wait, so the graph's state is written here after every step and read
back when the decision arrives (possibly by a different worker, after a
restart). The rows belong to the person whose run it is.

These tables are written only by `app.agent.checkpoint.SqlCheckpointSaver`.
The thread id is the run id.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin


class GraphCheckpoint(Base, TimestampMixin):
    __tablename__ = "graph_checkpoints"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(200), primary_key=True, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    checkpoint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    meta: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (Index("ix_graph_checkpoints_owner", "owner_id"),)


class GraphCheckpointWrite(Base, TimestampMixin):
    """A step's pending output, saved before the step is committed."""

    __tablename__ = "graph_checkpoint_writes"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(200), primary_key=True, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (Index("ix_graph_checkpoint_writes_owner", "owner_id"),)
