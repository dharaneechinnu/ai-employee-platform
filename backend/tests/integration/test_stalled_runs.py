"""A run whose worker went quiet is ended and reported, not left "running" for ever."""

# The fixtures are imported from the agent schedule tests, which is what makes
# them visible here; naming them as arguments looks like redefinition to ruff.
# ruff: noqa: F811
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.agent import Agent
from app.db.models.task import Run, RunEvent, RunStatus, Task, TaskStatus
from tests.integration.conftest import seed_person
from tests.integration.test_agent_schedule import (  # noqa: F401  (fixtures)
    AGENTS,
    NIGHTLY,
    _new,
    _person,
    queued,
    scripted,
)

CONVERSATIONS = "/api/v1/me/conversations"


def _quiet(minutes: float) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


async def _task(api: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    created = await api.post(CONVERSATIONS, json={"mode": "study"}, headers=headers)
    sent = await api.post(
        f"{CONVERSATIONS}/{created.json()['id']}/messages",
        json={"content": "Summarise my week"},
        headers=headers,
    )
    assert sent.status_code == 202, sent.text
    return uuid.UUID(sent.json()["task_id"])


async def _start_run(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    heartbeat: datetime | None,
    status: RunStatus = RunStatus.RUNNING,
) -> uuid.UUID:
    """The state a worker leaves behind: a run that started, then went quiet."""
    task = await session.scalar(select(Task).where(Task.id == task_id))
    assert task is not None
    task.status = TaskStatus.RUNNING
    run = Run(
        owner_id=task.owner_id,
        task_id=task_id,
        agent_id=task.agent_id,
        trigger=task.trigger,
        status=status,
        started_at=_quiet(30),
        heartbeat_at=heartbeat,
        worker_id="worker-that-died",
    )
    session.add(run)
    await session.commit()
    return run.id


async def _run(session: AsyncSession, run_id: uuid.UUID) -> Run:
    session.expire_all()
    run = await session.scalar(select(Run).where(Run.id == run_id))
    assert run is not None
    return run


async def test_a_run_that_has_gone_quiet_is_ended_and_the_person_is_told(
    api: AsyncClient, session: AsyncSession
) -> None:
    from app.workers.jobs.maintenance import reap_stalled_runs

    person = await seed_person(session, api, name="Meera")
    headers = {"Authorization": f"Bearer {person.token}"}
    task_id = await _task(api, headers)
    run_id = await _start_run(session, task_id, heartbeat=_quiet(20))

    assert await reap_stalled_runs({}) == 1

    run = await _run(session, run_id)
    assert run.status is RunStatus.FAILED and run.stop_cause == "stalled"
    assert run.ended_at is not None and run.error_message

    task = await session.scalar(select(Task).where(Task.id == task_id))
    assert task is not None and task.status is TaskStatus.FAILED

    # The chat says what happened, in plain words.
    convo = (await api.get(f"{CONVERSATIONS}/{task.conversation_id}", headers=headers)).json()
    reply = convo["messages"][-1]
    assert "stopped unexpectedly" in reply["error"]

    # And the run's log says so too.
    events = (await session.scalars(select(RunEvent).where(RunEvent.run_id == run_id))).all()
    stopped = [e for e in events if e.type == "run_stopped"]
    assert len(stopped) == 1 and stopped[0].payload["cause"] == "stalled"
    assert stopped[0].payload["worker"] == "worker-that-died"


async def test_a_run_that_is_still_alive_is_left_alone(
    api: AsyncClient, session: AsyncSession
) -> None:
    from app.workers.jobs.maintenance import reap_stalled_runs

    person = await seed_person(session, api, name="Meera")
    headers = {"Authorization": f"Bearer {person.token}"}
    run_id = await _start_run(session, await _task(api, headers), heartbeat=_quiet(1))

    assert await reap_stalled_runs({}) == 0

    assert (await _run(session, run_id)).status is RunStatus.RUNNING


async def test_the_quiet_time_is_the_setting_not_a_fixed_number(
    api: AsyncClient, session: AsyncSession
) -> None:
    from app.workers.jobs.maintenance import reap_stalled_runs

    person = await seed_person(session, api, name="Meera")
    headers = {"Authorization": f"Bearer {person.token}"}
    run_id = await _start_run(session, await _task(api, headers), heartbeat=_quiet(8))
    assert get_settings().run_stall_seconds == 600  # ten minutes

    assert await reap_stalled_runs({}) == 0  # 8 minutes is not long enough
    assert (await _run(session, run_id)).status is RunStatus.RUNNING


async def test_a_run_waiting_for_an_approval_is_not_a_stalled_run(
    api: AsyncClient, session: AsyncSession
) -> None:
    from app.workers.jobs.maintenance import reap_stalled_runs

    person = await seed_person(session, api, name="Meera")
    headers = {"Authorization": f"Bearer {person.token}"}
    run_id = await _start_run(
        session,
        await _task(api, headers),
        heartbeat=_quiet(120),
        status=RunStatus.AWAITING_APPROVAL,
    )

    assert await reap_stalled_runs({}) == 0
    assert (await _run(session, run_id)).status is RunStatus.AWAITING_APPROVAL


async def test_a_run_with_no_mark_at_all_is_judged_by_when_it_started(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Rows from before the mark existed have none: they must not live for ever."""
    from app.workers.jobs.maintenance import reap_stalled_runs

    person = await seed_person(session, api, name="Meera")
    headers = {"Authorization": f"Bearer {person.token}"}
    run_id = await _start_run(session, await _task(api, headers), heartbeat=None)

    assert await reap_stalled_runs({}) == 1  # started 30 minutes ago, never marked
    assert (await _run(session, run_id)).status is RunStatus.FAILED


async def test_a_second_sweep_does_not_end_the_same_run_twice(
    api: AsyncClient, session: AsyncSession
) -> None:
    from app.workers.jobs.maintenance import reap_stalled_runs

    person = await seed_person(session, api, name="Meera")
    headers = {"Authorization": f"Bearer {person.token}"}
    run_id = await _start_run(session, await _task(api, headers), heartbeat=_quiet(20))

    assert await reap_stalled_runs({}) == 1
    assert await reap_stalled_runs({}) == 0

    events = (await session.scalars(select(RunEvent).where(RunEvent.run_id == run_id))).all()
    assert len([e for e in events if e.type == "run_stopped"]) == 1


async def test_a_stalled_agent_run_is_reported_and_the_agent_can_run_again(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    from app.workers.jobs.maintenance import reap_stalled_runs

    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()
    started = (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).json()
    assert started["status"] == "started"
    await _start_run(session, uuid.UUID(started["task_id"]), heartbeat=_quiet(20))

    # While the dead run still looks alive, the agent refuses to start another.
    busy = (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).json()
    assert busy["status"] == "busy"

    assert await reap_stalled_runs({}) == 1

    session.expire_all()
    row = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(agent["id"])))
    assert row is not None and row.last_status == "failed"
    assert "stopped unexpectedly" in (row.last_summary or "")

    again: dict[str, Any] = (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).json()
    assert again["status"] == "started"  # no longer blocked by a run that is long dead
