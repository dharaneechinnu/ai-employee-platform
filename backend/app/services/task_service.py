"""Task creation, reading and cancellation.

Creating a task writes a row and queues a job; it never runs the agent.
An agent run takes minutes, and an HTTP request that waits that long
times out, freezes the screen and loses the work. The API answers in
milliseconds and the worker does the slow part.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.observability import get_logger
from app.db.models.ai_employee import AIEmployee, AIEmployeeVersion, EmployeeStatus
from app.db.models.task import (
    TERMINAL_STATUSES,
    EventType,
    LLMCall,
    Run,
    RunEvent,
    RunStatus,
    Task,
    TaskStatus,
    ToolInvocation,
)

log = get_logger(__name__)


@dataclass(slots=True)
class TaskWithRun:
    task: Task
    run: Run | None


class TaskService:
    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        self.session = session
        self.org_id = org_id

    # ------------------------------------------------------------- create

    async def create(
        self,
        *,
        employee_id: uuid.UUID,
        text: str,
        title: str | None,
        dry_run: bool,
        user_id: uuid.UUID,
    ) -> Task:
        employee = await self.session.scalar(
            select(AIEmployee).where(AIEmployee.id == employee_id, AIEmployee.org_id == self.org_id)
        )
        if employee is None:
            raise NotFoundError("No such AI Employee.")

        if employee.status not in (EmployeeStatus.ACTIVE, EmployeeStatus.DRAFT):
            raise ConflictError(
                f"{employee.name} is {employee.status} and cannot take tasks right now."
            )

        version = await self.session.scalar(
            select(AIEmployeeVersion)
            .where(AIEmployeeVersion.employee_id == employee_id)
            .order_by(AIEmployeeVersion.version_no.desc())
            .limit(1)
        )
        if version is None:
            raise ValidationError("That AI Employee has no configuration.")

        task = Task(
            org_id=self.org_id,
            employee_id=employee_id,
            # Pinned now. A later edit must not rewrite what this run did.
            employee_version_id=version.id,
            title=title or text[:200],
            input=text,
            dry_run=dry_run,
            created_by=user_id,
            status=TaskStatus.QUEUED,
        )
        self.session.add(task)
        await self.session.flush()

        log.info("task_created", task_id=str(task.id), employee_id=str(employee_id))
        return task

    # ------------------------------------------------------------- read

    async def get(self, task_id: uuid.UUID) -> TaskWithRun:
        task = await self.session.scalar(
            select(Task).where(Task.id == task_id, Task.org_id == self.org_id)
        )
        if task is None:
            raise NotFoundError("No such task.")

        run = await self.session.scalar(
            select(Run).where(Run.task_id == task_id).order_by(Run.attempt.desc()).limit(1)
        )
        return TaskWithRun(task=task, run=run)

    async def list_tasks(self, *, limit: int = 50) -> list[Task]:
        result = await self.session.scalars(
            select(Task)
            .where(Task.org_id == self.org_id)
            .order_by(Task.created_at.desc())
            .limit(limit)
        )
        return list(result.all())

    async def get_run(self, run_id: uuid.UUID) -> Run:
        run = await self.session.scalar(
            select(Run).where(Run.id == run_id, Run.org_id == self.org_id)
        )
        if run is None:
            raise NotFoundError("No such run.")
        return run

    async def events_after(self, run_id: uuid.UUID, after_seq: int = 0) -> list[RunEvent]:
        """Everything the client has not seen.

        A reconnecting browser says "I have up to 12" and gets 13
        onward, so nothing is lost and nothing is duplicated.
        """
        await self.get_run(run_id)  # proves ownership first
        result = await self.session.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
            .order_by(RunEvent.seq)
        )
        return list(result.all())

    async def invocations(self, run_id: uuid.UUID) -> list[ToolInvocation]:
        await self.get_run(run_id)
        result = await self.session.scalars(
            select(ToolInvocation)
            .where(ToolInvocation.run_id == run_id)
            .order_by(ToolInvocation.created_at)
        )
        return list(result.all())

    async def llm_calls(self, run_id: uuid.UUID) -> list[LLMCall]:
        await self.get_run(run_id)
        result = await self.session.scalars(
            select(LLMCall).where(LLMCall.run_id == run_id).order_by(LLMCall.created_at)
        )
        return list(result.all())

    # ------------------------------------------------------------- cancel

    async def request_cancel(self, task_id: uuid.UUID) -> Task:
        """Set a flag rather than killing anything.

        The loop checks it between steps, so a cancelled task stops at
        a clean boundary with its history intact instead of being
        severed mid tool call.
        """
        current = await self.get(task_id)
        task = current.task

        if task.status in TERMINAL_STATUSES:
            raise ConflictError(f"That task is already {task.status}.")

        task.cancel_requested = True
        if task.status == TaskStatus.QUEUED:
            # Never picked up, so nothing has to notice the flag.
            task.status = TaskStatus.CANCELLED
            if current.run is not None:
                current.run.status = RunStatus.CANCELLED

        return task


# ----------------------------------------------------------------- writer


class EventWriter:
    """Appends to the run event log, in order.

    Postgres first, then Redis. If the publish fails the event still
    exists and a reconnecting client replays it; the other order would
    show clients an event that is not in the permanent record.
    """

    def __init__(self, session: AsyncSession, run_id: uuid.UUID, org_id: uuid.UUID) -> None:
        self.session = session
        self.run_id = run_id
        self.org_id = org_id
        self._seq = 0

    async def append(self, type_: str, payload: dict[str, Any] | None = None) -> RunEvent:
        self._seq += 1
        event = RunEvent(
            run_id=self.run_id,
            org_id=self.org_id,
            seq=self._seq,
            type=type_,
            payload=_redact(payload or {}),
            created_at=datetime.now(UTC),
        )
        self.session.add(event)
        await self.session.flush()
        return event


# Applied on write, so a secret never enters the table at all.
# Redacting on read would leave the plaintext in the database for ever.
_SENSITIVE = {"api_key", "token", "password", "secret", "authorization", "credential", "key"}


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if any(marker in key.lower() for marker in _SENSITIVE):
            out[key] = "[redacted]"
        elif isinstance(value, dict):
            out[key] = _redact(value)
        else:
            out[key] = value
    return out


def estimate_cost(provider_key: str, model: str, prompt_tokens: int, output_tokens: int) -> Decimal:
    """Estimated cost in USD.

    With BYOK we never see the provider's invoice, so every figure
    derived from this must be labelled an estimate. Presenting it as a
    bill would be dishonest.
    """
    from app.agent.pricing import price_per_million

    price = price_per_million(provider_key, model)
    return (
        Decimal(prompt_tokens) * price.input_usd + Decimal(output_tokens) * price.output_usd
    ) / Decimal(1_000_000)


_ = EventType  # re-exported for callers building payloads
