"""Start the agents whose time has come.

Runs every minute. An agent is due when its schedule is on and
`next_run_at` has passed. Its next time is moved forward *before* the
run is started, in the same transaction, so a crash cannot make it fire
twice; and because the next time is worked out from now, a worker that
was down at 23:30 starts the agent once when it comes back, not once for
every minute it missed.

The runner re-checks the connections first. A broken link means the run
does not begin and the person is told which one to fix.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.agent.schedule import Schedule, next_run
from app.core.observability import get_logger
from app.db.models.agent import Agent
from app.db.session import get_sessionmaker
from app.services.agent_runner import AgentRunner
from app.services.live_feed import record_scheduler_event
from app.services.notification_service import NotificationService, notify_safely
from app.workers.queue import enqueue_task

log = get_logger(__name__)

BATCH = 50


async def dispatch_due_agents(ctx: dict[str, Any]) -> int:
    """Returns how many runs were started."""
    now = datetime.now(UTC)
    to_enqueue: list[uuid.UUID] = []

    async with get_sessionmaker()() as session:
        due = (
            await session.scalars(
                select(Agent)
                .where(
                    Agent.schedule_enabled.is_(True),
                    Agent.archived.is_(False),
                    Agent.next_run_at <= now,
                )
                .order_by(Agent.next_run_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()

        for agent in due:
            was_due = agent.next_run_at
            try:
                agent.next_run_at = next_run(Schedule.model_validate(agent.schedule), now)
            except ValueError:
                # A schedule nobody can read is switched off, loudly,
                # rather than retried every minute for ever.
                agent.schedule_enabled, agent.next_run_at = False, None
                log.warning("agent_schedule_invalid", agent_id=str(agent.id))
                continue

            # The live tree starts its story here; the runner adds the
            # connection check and the start (or why it did not start).
            await record_scheduler_event(
                session,
                owner_id=agent.owner_id,
                agent_id=agent.id,
                type_="agent_due",
                payload={
                    "name": agent.name,
                    "scheduled_for": was_due.isoformat() if was_due else None,
                },
            )
            result = await AgentRunner(session, agent.owner_id).start(
                agent, user_id=agent.owner_id, trigger="schedule"
            )
            if result.task is not None:
                to_enqueue.append(result.task.id)
            elif result.status == "needs_attention":
                await notify_safely(
                    NotificationService(session, agent.owner_id).agent_run_finished(
                        agent, status="needs_attention", summary=result.message
                    )
                )
            log.info("agent_due", agent_id=str(agent.id), outcome=result.status)

        await session.commit()

    for task_id in to_enqueue:
        await enqueue_task(task_id)
    return len(to_enqueue)
