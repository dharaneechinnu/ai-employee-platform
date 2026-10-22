"""Approvals: pause a run, wait for a human, resume it.

The hard part is that a run may wait hours. The worker cannot sit and
wait — it has other jobs — so the conversation so far is saved and
reloaded when the decision arrives. That is also why the run survives
a worker restart: the state is in Postgres, not in the process.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.observability import get_logger
from app.db.models.policy import Approval, ApprovalStatus, RunCheckpoint
from app.db.models.task import Run, RunStatus, Task, TaskStatus

log = get_logger(__name__)

APPROVAL_TTL_HOURS = 24


@dataclass(slots=True)
class PendingApproval:
    approval: Approval
    task_title: str | None


class ApprovalService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    async def create(
        self,
        *,
        run_id: uuid.UUID,
        tool_name: str,
        side_effect: str,
        proposed: dict[str, Any],
        state: dict[str, Any],
        pending_tool_call: dict[str, Any],
    ) -> Approval:
        approval = Approval(
            owner_id=self.owner_id,
            run_id=run_id,
            tool_name=tool_name,
            side_effect=side_effect,
            # The whole action, never a summary: a reviewer must be able
            # to read exactly what they are agreeing to.
            proposed=proposed,
            expires_at=datetime.now(UTC) + timedelta(hours=APPROVAL_TTL_HOURS),
        )
        self.session.add(approval)

        existing = await self.session.get(RunCheckpoint, run_id)
        if existing is not None:
            existing.state = state
            existing.pending_tool_call = pending_tool_call
        else:
            self.session.add(
                RunCheckpoint(
                    run_id=run_id,
                    owner_id=self.owner_id,
                    state=state,
                    pending_tool_call=pending_tool_call,
                )
            )

        run = await self.session.get(Run, run_id)
        if run is not None:
            run.status = RunStatus.AWAITING_APPROVAL
            task = await self.session.get(Task, run.task_id)
            if task is not None:
                task.status = TaskStatus.AWAITING_APPROVAL

        await self.session.flush()
        log.info("approval_requested", run_id=str(run_id), tool=tool_name)
        return approval

    async def list_pending(self) -> list[PendingApproval]:
        rows = await self.session.execute(
            select(Approval, Task)
            .join(Run, Run.id == Approval.run_id)
            .join(Task, Task.id == Run.task_id)
            .where(Approval.owner_id == self.owner_id, Approval.status == ApprovalStatus.PENDING)
            .order_by(Approval.created_at)
        )
        return [PendingApproval(approval=a, task_title=t.title) for a, t in rows.all()]

    async def get(self, approval_id: uuid.UUID) -> Approval:
        approval = await self.session.scalar(
            select(Approval).where(Approval.id == approval_id, Approval.owner_id == self.owner_id)
        )
        if approval is None:
            raise NotFoundError("No such approval.")
        return approval

    async def decide(
        self, *, approval_id: uuid.UUID, approve: bool, user_id: uuid.UUID
    ) -> Approval:
        approval = await self.get(approval_id)

        if approval.status is not ApprovalStatus.PENDING:
            raise ConflictError(f"That request was already {approval.status.value}.")

        if approval.expires_at <= datetime.now(UTC):
            approval.status = ApprovalStatus.EXPIRED
            await self._fail_run(approval.run_id, "The approval request expired.")
            raise ConflictError("That request has expired. Run the task again.")

        approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        approval.decided_by = user_id
        approval.decided_at = datetime.now(UTC)

        if not approve:
            # Rejection ends the run cleanly rather than leaving it
            # half-finished and waiting on nothing.
            await self._fail_run(approval.run_id, "A reviewer rejected the proposed action.")

        log.info(
            "approval_decided",
            approval_id=str(approval_id),
            approved=approve,
            tool=approval.tool_name,
        )
        return approval

    async def _fail_run(self, run_id: uuid.UUID, reason: str) -> None:
        run = await self.session.get(Run, run_id)
        if run is None:
            return

        run.status = RunStatus.FAILED
        run.stop_cause = "approval_denied"
        run.error_message = reason
        run.ended_at = datetime.now(UTC)

        task = await self.session.get(Task, run.task_id)
        if task is not None:
            task.status = TaskStatus.FAILED

    async def checkpoint(self, run_id: uuid.UUID) -> RunCheckpoint:
        checkpoint = await self.session.get(RunCheckpoint, run_id)
        if checkpoint is None:
            raise NotFoundError("That run has no saved state.")
        return checkpoint


async def expire_stale_approvals(session: AsyncSession) -> int:
    """Scheduled sweep.

    Without it, forgotten approvals pile up and hold runs open for
    ever. Failing clearly lets the user retry; waiting silently does
    not.
    """
    now = datetime.now(UTC)
    stale = (
        await session.scalars(
            select(Approval).where(
                Approval.status == ApprovalStatus.PENDING, Approval.expires_at <= now
            )
        )
    ).all()

    for approval in stale:
        approval.status = ApprovalStatus.EXPIRED

    if stale:
        run_ids = [a.run_id for a in stale]
        await session.execute(
            update(Run)
            .where(Run.id.in_(run_ids))
            .values(
                status=RunStatus.FAILED,
                stop_cause="approval_expired",
                error_message="No one answered the approval request within 24 hours.",
                ended_at=now,
            )
        )
        task_ids = [
            r.task_id for r in (await session.scalars(select(Run).where(Run.id.in_(run_ids)))).all()
        ]
        await session.execute(
            update(Task).where(Task.id.in_(task_ids)).values(status=TaskStatus.FAILED)
        )

    return len(stale)
