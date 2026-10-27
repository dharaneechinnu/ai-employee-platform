"""History: the list of past runs, its filters, and one run's detail.

The model is stubbed (see test_agent_schedule). What matters here: who
started a run is recorded, the list is the caller's own and newest first,
paging loses and repeats nothing, the filters narrow it, and the detail
carries the lanes, models and result the side panel needs.
"""

# The fixtures are imported from the agent schedule tests, which is what makes
# them visible here; naming them as arguments looks like redefinition to ruff.
# ruff: noqa: F811
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.task import Run
from tests.integration.conftest import seed_person
from tests.integration.test_agent_schedule import (  # noqa: F401  (fixtures)
    AGENTS,
    CONVERSATIONS,
    NIGHTLY,
    Scripted,
    _new,
    _person,
    _run_task,
    queued,
    scripted,
)

HISTORY = "/api/v1/me/history"


async def _agent_run(
    api: AsyncClient, headers: dict[str, str], agent_id: str, *, tool: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Run an agent now and let the worker finish it. Returns the run id."""
    # A key on a free plan costs nothing; these tests want a charged call.
    await api.put("/api/v1/me/providers/gemini/plan", json={"plan": "paid"}, headers=headers)
    Scripted.call_first = tool
    started = (await api.post(f"{AGENTS}/{agent_id}/run", headers=headers)).json()
    done = await _run_task(uuid.UUID(started["task_id"]))
    return str(done["run_id"]), dict(started)


async def _chat_run(api: AsyncClient, headers: dict[str, str], text: str) -> str:
    await api.put("/api/v1/me/providers/gemini/plan", json={"plan": "paid"}, headers=headers)
    created = await api.post(CONVERSATIONS, json={"mode": "study"}, headers=headers)
    sent = await api.post(
        f"{CONVERSATIONS}/{created.json()['id']}/messages", json={"content": text}, headers=headers
    )
    assert sent.status_code == 202, sent.text
    return str((await _run_task(uuid.UUID(sent.json()["task_id"])))["run_id"])


async def _page(api: AsyncClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = await api.get(f"{HISTORY}/runs", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_who_started_a_run_is_recorded(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    from app.workers.jobs.scheduler import dispatch_due_agents

    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()

    manual_id, _ = await _agent_run(api, headers, agent["id"])
    chat_id = await _chat_run(api, headers, "What day is it?")

    await session.execute(
        update(Agent)
        .where(Agent.id == uuid.UUID(agent["id"]))
        .values(next_run_at=datetime.now(UTC) - timedelta(minutes=2))
    )
    await session.commit()
    assert await dispatch_due_agents({}) == 1
    scheduled_id = (await _run_task(queued[-1]))["run_id"]

    items = {i["id"]: i for i in (await _page(api, headers))["items"]}
    assert items[manual_id]["trigger"] == "manual"
    assert items[str(scheduled_id)]["trigger"] == "schedule"
    assert items[chat_id]["trigger"] == "chat"
    assert items[manual_id]["agent_name"] == "Night Owl" and items[chat_id]["agent_id"] is None

    only = await _page(api, headers, trigger="schedule")
    assert [i["id"] for i in only["items"]] == [str(scheduled_id)]


async def test_the_list_is_newest_first_and_pages_without_gaps_or_repeats(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    made = [(await _agent_run(api, headers, agent["id"]))[0] for _ in range(5)]

    first = await _page(api, headers, limit=2)
    assert [i["id"] for i in first["items"]] == made[::-1][:2]
    assert first["next"]
    second = await _page(api, headers, limit=2, before=first["next"])
    third = await _page(api, headers, limit=2, before=second["next"])
    seen = [i["id"] for p in (first, second, third) for i in p["items"]]
    assert seen == made[::-1]
    assert third["next"] is None

    bad = await api.get(f"{HISTORY}/runs", params={"before": "nonsense"}, headers=headers)
    assert bad.status_code == 422


async def test_filters_narrow_the_list(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    _, headers = await _person(api, session)
    owl = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    other = (await api.post(AGENTS, json=_new(name="Reader"), headers=headers)).json()
    owl_run, _ = await _agent_run(api, headers, owl["id"])
    other_run, _ = await _agent_run(api, headers, other["id"])
    chat_run = await _chat_run(api, headers, "Plan my weekend")

    async def ids(**params: Any) -> set[str]:
        return {i["id"] for i in (await _page(api, headers, **params))["items"]}

    everything = {owl_run, other_run, chat_run}
    assert await ids(agent_id=owl["id"]) == {owl_run}
    assert await ids(status="completed") == everything
    assert await ids(status="failed") == set()
    assert await ids(q="reader") == {other_run}  # the agent's name
    assert await ids(q="weekend") == {chat_run}  # the task's title
    assert await ids(q="nothing to report") == everything  # the result
    assert await ids(q="100%") == set()  # % is not a wildcard
    assert await ids(model="gemini-2.0-flash") == everything
    assert await ids(model="no-such-model") == set()
    soon = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert await ids(since=soon) == set()
    assert await ids(until=soon) == everything

    # The stub model is priced, so these runs were charged for.
    assert await ids(cost="paid") == everything
    assert await ids(cost="free") == set()
    assert (await api.get(f"{HISTORY}/models", headers=headers)).json() == ["gemini-2.0-flash"]


async def test_the_detail_has_lanes_models_and_the_result(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    run_id, started = await _agent_run(api, headers, agent["id"], tool="current_time")

    detail = (await api.get(f"{HISTORY}/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "completed"
    assert detail["result"] == "Added 0 events. Nothing to report."
    assert detail["conversation_id"] == started["conversation_id"]
    assert detail["can_run_again"] is True
    assert detail["duration_seconds"] is not None
    model = detail["models"][0]
    assert model["model"] == "gemini-2.0-flash" and model["plan"] == "paid"
    assert float(model["estimated_cost_usd"]) > 0

    lanes = detail["lanes"]
    assert lanes[0]["kind"] == "agent" and lanes[0]["label"] == "Night Owl"
    tools = [lane for lane in lanes if lane["kind"] == "tool"]
    assert [t["label"] for t in tools] == ["Current time"]
    assert 0 <= tools[0]["start_ms"] <= tools[0]["end_ms"] <= lanes[0]["end_ms"]

    # An agent that was removed can still be read, but not run again.
    await api.delete(f"{AGENTS}/{agent['id']}", headers=headers)
    again = (await api.get(f"{HISTORY}/runs/{run_id}", headers=headers)).json()
    assert again["can_run_again"] is False


async def test_a_failed_run_shows_its_reason_as_the_summary(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    run_id, _ = await _agent_run(api, headers, agent["id"])
    await session.execute(
        update(Run)
        .where(Run.id == uuid.UUID(run_id))
        .values(status="failed", error_message="The Google Sheets link expired.")
    )
    await session.commit()

    item = (await _page(api, headers, status="failed"))["items"][0]
    assert item["summary"] == "The Google Sheets link expired."


async def test_one_person_cannot_see_anothers_runs(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    _, mine = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=mine)).json()
    run_id, _ = await _agent_run(api, mine, agent["id"])

    other = await seed_person(session, api, name="Ben")
    theirs = {"Authorization": f"Bearer {other.token}"}

    assert (await _page(api, theirs))["items"] == []
    assert (await _page(api, theirs, agent_id=agent["id"]))["items"] == []
    assert (await _page(api, theirs, q="Night Owl"))["items"] == []
    assert (await api.get(f"{HISTORY}/runs/{run_id}", headers=theirs)).status_code == 404
    assert (await api.get(f"{HISTORY}/models", headers=theirs)).json() == []
    assert (await api.get(f"{HISTORY}/runs")).status_code == 401
    assert len((await _page(api, mine))["items"]) == 1
