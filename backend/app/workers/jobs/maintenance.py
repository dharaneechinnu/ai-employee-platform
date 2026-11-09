"""Scheduled housekeeping."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.agent.checkpoint import purge_stale
from app.config import get_settings
from app.core.observability import get_logger
from app.db.models.task import Run, RunStatus
from app.db.session import get_sessionmaker
from app.services.approval_service import expire_stale_approvals
from app.services.task_service import EventWriter

log = get_logger(__name__)

# One sweep deals with at most this many dead runs; the next sweep takes the rest.
STALLED_BATCH = 50


async def expire_approvals(ctx: dict[str, Any]) -> int:
    """Fail runs whose approval nobody answered in time.

    Without this sweep a forgotten request holds its run open for ever,
    and an approval link in someone's inbox would still look live.
    """
    async with get_sessionmaker()() as session:
        expired = await expire_stale_approvals(session)
        purged = await purge_stale(session)
        await session.commit()
    if purged:
        log.info("checkpoints_purged", count=purged)
    if expired:
        log.info("approvals_expired", count=expired)
    return expired


def _stalled_before(now: datetime) -> datetime:
    return now - timedelta(seconds=get_settings().run_stall_seconds)


async def reap_stalled_runs(ctx: dict[str, Any]) -> int:
    """End runs whose worker has gone quiet.

    A running run writes a "still alive" mark with every step. If the worker
    dies or freezes the mark stops, and nothing else would ever notice: the run
    would stay "running" for ever, the person would hear nothing, and an agent's
    next scheduled run would be skipped because "the last run is still going".

    A run with no mark for `run_stall_seconds` is ended as failed, with a plain
    message in its chat, an event in its log and (for an agent) the usual
    notification. It is not started again on its own: it may already have
    changed something, and running it twice is the mistake the handoff note
    exists to prevent. The person, or the agent's next schedule, decides.

    Runs waiting for an approval are not running, so they are left alone.
    """
    cutoff = _stalled_before(datetime.now(UTC))
    maker = get_sessionmaker()
    async with maker() as session:
        ids = (
            await session.scalars(
                select(Run.id)
                .where(
                    Run.status == RunStatus.RUNNING,
                    func.coalesce(Run.heartbeat_at, Run.started_at) < cutoff,
                )
                .order_by(func.coalesce(Run.heartbeat_at, Run.started_at))
                .limit(STALLED_BATCH)
            )
        ).all()

    ended = 0
    for run_id in ids:
        if await _end_stalled(run_id, cutoff):
            ended += 1
    if ended:
        log.warning("stalled_runs_ended", count=ended)
    return ended


async def _end_stalled(run_id: uuid.UUID, cutoff: datetime) -> bool:
    """End one dead run in its own transaction. False when it is not (or no
    longer) stalled: it finished, or another sweep got there first."""
    # Imported here: the run module pulls in the whole agent stack.
    from app.workers.jobs.agent_run import _finish

    async with get_sessionmaker()() as session:
        run = await session.scalar(
            select(Run)
            .where(
                Run.id == run_id,
                Run.status == RunStatus.RUNNING,
                func.coalesce(Run.heartbeat_at, Run.started_at) < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return False

        silent_since = run.heartbeat_at or run.started_at
        await EventWriter(session, run.id, run.owner_id).append(
            "run_stopped",
            {
                "cause": "stalled",
                "last_seen": silent_since.isoformat() if silent_since else None,
                "worker": run.worker_id,
            },
        )
        await _finish(
            session,
            run,
            run.task_id,
            RunStatus.FAILED,
            stop_cause="stalled",
            error="The worker running this stopped responding.",
        )
        log.warning(
            "run_stalled", run_id=str(run.id), worker=run.worker_id, last_seen=str(silent_since)
        )
        return True
