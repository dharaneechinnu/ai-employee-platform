"""The account's live stream and the agent tree's starting picture.

What matters here: the scheduler's steps (due, connections checked,
started or not) and a run's own events arrive in one feed, in order; a
person only ever sees their own; and a client that reconnects with its
position gets the rest and nothing twice.
"""

# The fixtures are imported from the agent schedule tests, which is what makes
# them visible here; naming them as arguments looks like redefinition to ruff.
# ruff: noqa: F811
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from tests.integration.conftest import seed_person
from tests.integration.test_agent_schedule import (  # noqa: F401  (fixtures)
    AGENTS,
    NIGHTLY,
    SHEET,
    Scripted,
    _new,
    _person,
    _run_task,
    queued,
    scripted,
)

LIVE = "/api/v1/me/live"
TREE = f"{AGENTS}/tree"


async def _watch(
    api: AsyncClient, headers: dict[str, str], since: str = "0.0"
) -> list[dict[str, Any]]:
    """Read the stream from `since` until it closes itself (one second)."""
    response = await api.get(
        LIVE, params={"last_event_id": since, "max_seconds": 1}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


async def _make_due(session: AsyncSession, agent_id: str) -> None:
    session.expire_all()
    row = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    assert row is not None
    row.next_run_at = datetime.now(UTC) - timedelta(minutes=2)
    await session.commit()


async def test_a_scheduled_start_shows_due_then_checked_then_started(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    from app.workers.jobs.scheduler import dispatch_due_agents

    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()
    await _make_due(session, agent["id"])
    assert await dispatch_due_agents({}) == 1

    events = await _watch(api, headers)
    assert [e["type"] for e in events] == ["agent_due", "connections_checked", "agent_started"]
    assert {e["agent_id"] for e in events} == {agent["id"]}
    assert events[1]["ok"] is True
    assert events[2]["trigger"] == "schedule"
    assert events[2]["task_id"] == str(queued[0])


async def test_a_broken_link_is_named_and_nothing_starts(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    from app.workers.jobs.scheduler import dispatch_due_agents

    _, headers = await _person(api, session)
    agent = (
        await api.post(
            AGENTS,
            json=_new(tools=["sheets_read"], scope={"sheet_ids": [SHEET]}, schedule=NIGHTLY),
            headers=headers,
        )
    ).json()
    await _make_due(session, agent["id"])
    await dispatch_due_agents({})

    events = await _watch(api, headers)
    assert [e["type"] for e in events] == ["agent_due", "connections_checked"]
    assert events[1]["ok"] is False
    assert events[1]["broken"] and "Google Workspace" in events[1]["message"]
    assert queued == []


async def test_run_now_writes_the_same_steps_without_a_due(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    assert (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).status_code == 200

    events = await _watch(api, headers)
    assert [e["type"] for e in events] == ["connections_checked", "agent_started"]
    assert events[1]["trigger"] == "manual"

    # A second press while the first is still going is skipped, and says so.
    await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)
    again = await _watch(api, headers)
    assert [e["type"] for e in again][-1] == "agent_skipped"


async def test_a_runs_own_events_join_the_feed_with_their_agent(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)
    Scripted.call_first = "current_time"
    await _run_task(queued[0])

    events = await _watch(api, headers)
    kinds = [e["type"] for e in events]
    assert kinds[:2] == ["connections_checked", "agent_started"]
    assert "run_started" in kinds and "tool_call" in kinds and "run_finished" in kinds
    run_events = [e for e in events if e["run_id"]]
    assert {e["agent_id"] for e in run_events} == {agent["id"]}
    assert {e["task_id"] for e in run_events} == {str(queued[0])}
    # The tree needs to know which tool ran, not what it was given.
    assert all("arguments" not in e for e in run_events)
    assert next(e for e in events if e["type"] == "tool_call")["tool"] == "current_time"


async def test_a_reconnecting_client_gets_only_what_it_missed(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)

    first = await api.get(LIVE, params={"last_event_id": "0.0", "max_seconds": 1}, headers=headers)
    ids = [line.removeprefix("id: ") for line in first.text.splitlines() if line.startswith("id: ")]
    assert len(ids) == 1  # the position rides on the last frame of the batch

    assert await _watch(api, headers, since=ids[-1]) == []

    # The header browsers send on their own works the same way.
    via_header = await api.get(
        LIVE, params={"max_seconds": 1}, headers={**headers, "Last-Event-ID": ids[-1]}
    )
    assert "data:" not in via_header.text


async def test_a_new_viewer_sees_only_what_happens_from_now(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)

    fresh = await api.get(LIVE, params={"max_seconds": 1}, headers=headers)
    assert "data:" not in fresh.text


async def test_nobody_sees_anybody_elses_events(api: AsyncClient, session: AsyncSession) -> None:
    from app.workers.jobs.scheduler import dispatch_due_agents

    _, mine = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=mine)).json()
    await _make_due(session, agent["id"])
    await dispatch_due_agents({})

    other = await seed_person(session, api)
    theirs = {"Authorization": f"Bearer {other.token}"}
    assert await _watch(api, theirs) == []
    tree = (await api.get(TREE, headers=theirs)).json()
    assert tree["agents"] == [] and tree["recent_scheduler"] == []


async def test_the_stream_needs_a_signed_in_person(api: AsyncClient) -> None:
    assert (await api.get(LIVE)).status_code == 401
    assert (await api.get(TREE)).status_code == 401


async def test_the_tree_reports_next_run_state_and_the_helpers(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    _, headers = await _person(api, session)
    nightly = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()
    plain = (await api.post(AGENTS, json=_new(name="Plain"), headers=headers)).json()

    tree = (await api.get(TREE, headers=headers)).json()
    by_id = {a["id"]: a for a in tree["agents"]}
    assert by_id[nightly["id"]]["state"] == "idle"
    assert by_id[nightly["id"]]["next_run_at"] is not None
    assert by_id[nightly["id"]]["schedule_text"]
    assert by_id[plain["id"]]["next_run_at"] is None
    assert tree["scheduler"]["next_agent_id"] == nightly["id"]
    assert tree["scheduler"]["scheduled_count"] == 1
    assert tree["lead"]["state"] == "idle"
    # Stable ids for the built-in helpers.
    assert {"researcher", "analyst", "writer", "critic", "developer"} <= {
        h["key"] for h in tree["helpers"]
    }

    # A run that has been started and not yet finished makes its agent "working".
    await api.post(f"{AGENTS}/{plain['id']}/run", headers=headers)
    working = (await api.get(TREE, headers=headers)).json()
    row = next(a for a in working["agents"] if a["id"] == plain["id"])
    assert row["state"] == "working" and row["active_task_id"] == str(queued[0])
    assert [e["type"] for e in working["recent_scheduler"]][-1] == "agent_started"
    assert working["cursor"].count(".") == 1
