"""The self-contained steps of one run, pulled out of `agent_run._execute`.

`_execute` reads as the order of events (claim, pick the AI, pick the
tools, run, finish). Each step that has a rule of its own lives here, so
the rule can be read, and tested, without the rest of the run around it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.team import AskSpecialist
from app.agent.tools.base import Tool
from app.agent.tools.packs.builder import ProposeAgent
from app.db.models.policy import Approval, ApprovalStatus, PolicySetting, RunCheckpoint
from app.db.models.task import Run, RunStatus, Task, TaskStatus
from app.services.policy_service import PolicyResolver


async def claim_run(session: AsyncSession, task: Task, *, worker_id: str) -> Run:
    """Mark the task running and return its run row.

    A task resumed after an approval continues the paused run: a new row
    would orphan the checkpoint, which is keyed by run id, and the
    approved call would be lost.
    """
    run: Run | None = None
    if task.status is TaskStatus.AWAITING_APPROVAL:
        run = await session.scalar(
            select(Run)
            .where(Run.task_id == task.id, Run.status == RunStatus.AWAITING_APPROVAL)
            .order_by(Run.attempt.desc())
            .limit(1)
        )
        if run is not None:
            run.status = RunStatus.RUNNING
            run.heartbeat_at = datetime.now(UTC)

    if run is None:
        run = Run(
            owner_id=task.owner_id,
            task_id=task.id,
            attempt=1,
            status=RunStatus.RUNNING,
            started_at=datetime.now(UTC),
            heartbeat_at=datetime.now(UTC),
            worker_id=worker_id,
        )
        session.add(run)

    task.status = TaskStatus.RUNNING
    await session.flush()
    return run


def policy_check(
    resolver: PolicyResolver, *, unattended: bool, team_on: bool
) -> Callable[[str], tuple[str, str]]:
    """The permission check for the lead's own tool calls."""

    def check(tool_name: str) -> tuple[str, str]:
        if tool_name == ProposeAgent.name:
            return "auto", "it only shows a draft; nothing is created until the person agrees"
        if tool_name == AskSpecialist.name and team_on:
            # Specialists can only read; their own steps are checked one by one.
            return "auto", "team mode is on for this conversation"
        decision = resolver.evaluate(tool_name)
        if unattended and decision.setting is PolicySetting.ASK:
            return "blocked", "it needs approval, and no one is there to give it"
        return decision.setting.value, decision.reason

    return check


async def take_approved_call(
    session: AsyncSession, run_id: uuid.UUID
) -> tuple[RunCheckpoint | None, dict[str, Any] | None]:
    """The saved state of a paused run, and the call a person approved.

    The checkpoint is consumed once the approval is found, so a later
    pause in the same run does not replay the call a second time.
    """
    checkpoint = await session.get(RunCheckpoint, run_id)
    if checkpoint is None:
        return None, None
    approval = await session.scalar(
        select(Approval)
        .where(Approval.run_id == run_id, Approval.status == ApprovalStatus.APPROVED)
        .order_by(Approval.decided_at.desc())
        .limit(1)
    )
    if approval is None:
        return checkpoint, None
    approved = checkpoint.pending_tool_call
    await session.delete(checkpoint)
    await session.flush()
    return checkpoint, approved


def narrow_to_agent(tools: list[type[Tool]], agent_tools: list[str] | None) -> list[type[Tool]]:
    """An agent can only narrow what Permissions already allow."""
    if agent_tools is None:
        return tools
    allowed = set(agent_tools)
    return [t for t in tools if t.name in allowed]
