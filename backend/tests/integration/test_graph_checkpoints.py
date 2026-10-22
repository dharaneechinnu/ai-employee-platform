"""Step 4c with the real database: where the paused state lives, what survives a
restart, who can read it, and how runs paused the old way carry on."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.checkpoint import SqlCheckpointSaver
from app.db.models.checkpoint import GraphCheckpoint, GraphCheckpointWrite
from app.db.models.policy import RunCheckpoint
from app.db.models.task import Run
from tests.integration.test_policy_and_approvals import (
    SendsThenAnswers,
    _run,
    _say,
    _setup,
)


def use_loop(monkeypatch: pytest.MonkeyPatch, *, graph: bool) -> None:
    import app.workers.jobs.agent_run as job

    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: SendsThenAnswers(api_key))
    monkeypatch.setattr(
        job,
        "get_settings",
        lambda: SimpleNamespace(agent_supervisor=False, agent_checkpointer=graph),
    )


async def count(session: AsyncSession, table: type) -> int:
    await session.rollback()  # see rows other connections committed since
    return int(await session.scalar(select(func.count()).select_from(table)) or 0)


async def paused_run(api: AsyncClient, session: AsyncSession) -> tuple[dict[str, str], str, str]:
    headers = await _setup(api, session)
    task_id = await _say(api, headers, "Reply to the customer")
    assert (await _run(task_id))["status"] == "awaiting_approval"
    approval = (await api.get("/api/v1/me/approvals", headers=headers)).json()[0]
    return headers, task_id, approval["id"]


async def test_a_paused_run_is_saved_by_the_graph_not_the_old_snapshot(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_loop(monkeypatch, graph=True)
    await paused_run(api, session)

    assert await count(session, GraphCheckpoint) > 0
    assert await count(session, RunCheckpoint) == 0


async def test_the_old_loop_still_uses_the_snapshot(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_loop(monkeypatch, graph=False)
    await paused_run(api, session)

    assert await count(session, RunCheckpoint) == 1
    assert await count(session, GraphCheckpoint) == 0


async def test_a_paused_run_survives_a_worker_restart(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_loop(monkeypatch, graph=True)
    headers, task_id, approval_id = await paused_run(api, session)

    # The worker process dies: its pools and everything it held in memory go.
    from app.db.session import dispose_engine

    await dispose_engine()

    await api.post(f"/api/v1/me/approvals/{approval_id}/approve", headers=headers)
    await _run(task_id)  # a brand-new worker picks it up

    done = (await api.get(f"/api/v1/me/tasks/{task_id}", headers=headers)).json()
    assert done["status"] == "completed"
    assert done["run"]["output"] == "Email handled."


async def test_a_finished_run_leaves_nothing_saved(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_loop(monkeypatch, graph=True)
    headers, task_id, approval_id = await paused_run(api, session)
    await api.post(f"/api/v1/me/approvals/{approval_id}/approve", headers=headers)
    await _run(task_id)

    assert await count(session, GraphCheckpoint) == 0
    assert await count(session, GraphCheckpointWrite) == 0


async def test_rejecting_forgets_the_saved_state(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_loop(monkeypatch, graph=True)
    headers, task_id, approval_id = await paused_run(api, session)
    assert await count(session, GraphCheckpoint) > 0

    await api.post(f"/api/v1/me/approvals/{approval_id}/reject", headers=headers)

    assert await count(session, GraphCheckpoint) == 0
    failed = (await api.get(f"/api/v1/me/tasks/{task_id}", headers=headers)).json()
    assert failed["status"] == "failed"


async def test_an_expired_approval_forgets_the_saved_state(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.db.models.policy import Approval
    from app.services.approval_service import expire_stale_approvals

    use_loop(monkeypatch, graph=True)
    await paused_run(api, session)
    approval = (await session.scalars(select(Approval))).one()
    approval.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await session.commit()

    assert await expire_stale_approvals(session) == 1
    await session.commit()
    assert await count(session, GraphCheckpoint) == 0


async def test_a_run_paused_the_old_way_resumes_the_old_way_after_the_switch(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The upgrade must not strand a run that is waiting for a person."""
    use_loop(monkeypatch, graph=False)
    headers, task_id, approval_id = await paused_run(api, session)
    assert await count(session, RunCheckpoint) == 1

    use_loop(monkeypatch, graph=True)  # the switch is flipped while it waits
    await api.post(f"/api/v1/me/approvals/{approval_id}/approve", headers=headers)
    await _run(task_id)

    done = (await api.get(f"/api/v1/me/tasks/{task_id}", headers=headers)).json()
    assert done["status"] == "completed"
    assert done["run"]["output"] == "Email handled."


async def test_one_person_cannot_read_anothers_saved_state(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.session import get_sessionmaker

    use_loop(monkeypatch, graph=True)
    await paused_run(api, session)
    run_id = str((await session.scalars(select(Run.id))).one())
    config = {"configurable": {"thread_id": run_id}}

    stranger = SqlCheckpointSaver(get_sessionmaker(), uuid.uuid4())
    assert await stranger.aget_tuple(config) is None
    assert [c async for c in stranger.alist(config)] == []

    owner_id = (await session.scalars(select(Run.owner_id))).one()
    owner = SqlCheckpointSaver(get_sessionmaker(), owner_id)
    saved = await owner.aget_tuple(config)
    assert saved is not None
    assert saved.checkpoint["channel_values"]["messages"]  # the conversation so far

    # And a stranger's delete does not touch it.
    await stranger.adelete_thread(run_id)
    assert await owner.aget_tuple(config) is not None


async def test_a_chat_that_never_pauses_works_with_the_graph_loop(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The graph loop is the whole run now, not only the paused part."""
    use_loop(monkeypatch, graph=True)
    headers = await _setup(api, session)
    await api.put(
        "/api/v1/me/policies",
        json={
            "scope": "tool",
            "scope_value": "send_email",
            "side_effect": None,
            "setting": "blocked",
        },
        headers=headers,
    )
    task_id = await _say(api, headers, "Reply to the customer")
    await _run(task_id)

    done = (await api.get(f"/api/v1/me/tasks/{task_id}", headers=headers)).json()
    assert done["status"] == "completed"
    assert await count(session, GraphCheckpoint) == 0
