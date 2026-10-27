"""One live feed for the whole account.

The agent tree shows many agents at once, so it cannot hold one stream
per run. This reads the two append-only logs a person owns, the run
events and the scheduler events, in order, and hands them on as one
feed. Every query is filtered by owner; nothing here takes an owner from
a caller's input.

A position in the feed is a `Cursor`: the last id seen in each log. It
travels as text in the stream's `id:` line, so a browser that drops and
reconnects says where it was and loses nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.task import Run, RunEvent, SchedulerEvent, Task

BATCH = 200
# Tool arguments can be long and are of no use to the tree, which only
# needs to know which tool ran.
_DROPPED = {"arguments"}


@dataclass(frozen=True, slots=True)
class Cursor:
    run_events: int = 0
    scheduler_events: int = 0

    def __str__(self) -> str:
        return f"{self.run_events}.{self.scheduler_events}"

    @classmethod
    def parse(cls, text: str | None) -> Cursor | None:
        """None for anything that is not a cursor we handed out."""
        if not text:
            return None
        left, _, right = text.partition(".")
        if not (left.isdigit() and right.isdigit()):
            return None
        return cls(int(left), int(right))


async def record_scheduler_event(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    agent_id: uuid.UUID,
    type_: str,
    payload: dict[str, Any] | None = None,
    task_id: uuid.UUID | None = None,
) -> None:
    session.add(
        SchedulerEvent(
            owner_id=owner_id,
            agent_id=agent_id,
            task_id=task_id,
            type=type_,
            payload=payload or {},
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()


class LiveFeed:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    async def now(self) -> Cursor:
        """The end of both logs: where a new viewer starts watching."""
        runs = await self.session.scalar(
            select(func.max(RunEvent.id)).where(RunEvent.owner_id == self.owner_id)
        )
        sched = await self.session.scalar(
            select(func.max(SchedulerEvent.id)).where(SchedulerEvent.owner_id == self.owner_id)
        )
        return Cursor(runs or 0, sched or 0)

    async def after(self, cursor: Cursor) -> tuple[list[dict[str, Any]], Cursor]:
        """Everything newer than `cursor`, oldest first, and the new cursor."""
        run_rows = (
            await self.session.execute(
                # A run belongs to an agent when its schedule or Run now
                # started it, or when it is a turn of that agent's own chat.
                select(RunEvent, Run.task_id, func.coalesce(Task.agent_id, Conversation.agent_id))
                .join(Run, Run.id == RunEvent.run_id)
                .join(Task, Task.id == Run.task_id)
                .join(Conversation, Conversation.id == Task.conversation_id)
                .where(
                    RunEvent.owner_id == self.owner_id,
                    Run.owner_id == self.owner_id,
                    RunEvent.id > cursor.run_events,
                )
                .order_by(RunEvent.id)
                .limit(BATCH)
            )
        ).all()
        sched_rows = (
            await self.session.scalars(
                select(SchedulerEvent)
                .where(
                    SchedulerEvent.owner_id == self.owner_id,
                    SchedulerEvent.id > cursor.scheduler_events,
                )
                .order_by(SchedulerEvent.id)
                .limit(BATCH)
            )
        ).all()

        merged: list[tuple[datetime, dict[str, Any]]] = []
        for event, task_id, agent_id in run_rows:
            body = {k: v for k, v in event.payload.items() if k not in _DROPPED}
            merged.append(
                (
                    event.created_at,
                    {
                        **body,
                        "type": event.type,
                        "at": event.created_at.isoformat(),
                        "seq": event.seq,
                        "run_id": str(event.run_id),
                        "task_id": str(task_id),
                        "agent_id": str(agent_id) if agent_id else None,
                    },
                )
            )
        for sched in sched_rows:
            merged.append(
                (
                    sched.created_at,
                    {
                        **sched.payload,
                        "type": sched.type,
                        "at": sched.created_at.isoformat(),
                        "run_id": None,
                        "task_id": str(sched.task_id) if sched.task_id else None,
                        "agent_id": str(sched.agent_id),
                    },
                )
            )
        merged.sort(key=lambda pair: pair[0])

        newest = Cursor(
            run_rows[-1][0].id if run_rows else cursor.run_events,
            sched_rows[-1].id if sched_rows else cursor.scheduler_events,
        )
        return [body for _, body in merged], newest

    async def recent_scheduler_events(self, since: datetime) -> list[dict[str, Any]]:
        """What the scheduler has just done, so a tree opened mid-start
        shows where that start has got to."""
        rows = (
            await self.session.scalars(
                select(SchedulerEvent)
                .where(SchedulerEvent.owner_id == self.owner_id, SchedulerEvent.created_at >= since)
                .order_by(SchedulerEvent.id)
                .limit(100)
            )
        ).all()
        return [
            {
                **row.payload,
                "type": row.type,
                "at": row.created_at.isoformat(),
                "run_id": None,
                "task_id": str(row.task_id) if row.task_id else None,
                "agent_id": str(row.agent_id),
            }
            for row in rows
        ]
