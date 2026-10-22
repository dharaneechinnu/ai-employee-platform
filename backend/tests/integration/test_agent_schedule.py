"""Agents that run on their own: the schedule, Run now, and the nightly check.

The model is stubbed. What is tested is the platform around it: that a
schedule is validated and moves forward, that a run does not start when
a link in its chain is broken, that nothing runs twice, and that an
unattended run can never wait for an approval nobody will give.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from app.db.models.agent import Agent
from app.db.models.policy import Approval
from app.db.models.task import Task
from tests.integration.conftest import seed_person

AGENTS = "/api/v1/me/agents"
CONVERSATIONS = "/api/v1/me/conversations"
SHEET = "1duLbxa70UPyCCa2y33F-VpOGPWH4XLxAbt-U3Ylu1KI"

NIGHTLY = {"frequency": "daily", "time": "23:30", "timezone": "Asia/Kolkata"}


def _new(**over: Any) -> dict[str, Any]:
    return {
        "name": "Night Owl",
        "description": "Checks the date every night.",
        "instructions": "You are a night checker. Tell me today's date and one fact about it.",
        "tools": ["current_time"],
        **over,
    }


class Scripted(LLMProvider):
    """Answers at once, or first calls the tool named in `call_first`."""

    provider_key = "gemini"
    call_first: ClassVar[str | None] = None
    seen: ClassVar[list[dict[str, Any]]] = []

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        messages: list[Message] = kwargs["messages"]
        Scripted.seen.append({"tools": [t.name for t in kwargs.get("tools") or []]})
        if Scripted.call_first and not any(m.role is Role.TOOL for m in messages):
            reply = Message(
                role=Role.ASSISTANT,
                content=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name=Scripted.call_first,
                        arguments={
                            "spreadsheet": SHEET,
                            "tab": "Events",
                            "rows": [["Chennai React", "2026-11-02"]],
                        },
                    )
                ],
            )
            stop = StopReason.TOOL_USE
        else:
            reply = Message(role=Role.ASSISTANT, content="Added 0 events. Nothing to report.")
            stop = StopReason.END_TURN
        return LLMReply(
            message=reply,
            stop_reason=stop,
            usage=Usage(prompt_tokens=50, output_tokens=10),
            model="gemini-2.0-flash",
            latency_ms=3,
        )

    async def check(self, model: str) -> None:
        return None


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.workers.jobs.agent_run as job

    Scripted.call_first, Scripted.seen = None, []
    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: Scripted(api_key))


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Stands in for the worker queue, and records what was queued."""
    jobs: list[uuid.UUID] = []

    async def fake_enqueue(task_id: uuid.UUID, **_: Any) -> str:
        jobs.append(task_id)
        return "job"

    import app.api.v1.routes.agents as routes
    import app.workers.jobs.scheduler as scheduler

    monkeypatch.setattr(routes, "enqueue_task", fake_enqueue)
    monkeypatch.setattr(scheduler, "enqueue_task", fake_enqueue)
    return jobs


async def _person(api: AsyncClient, session: AsyncSession) -> tuple[uuid.UUID, dict[str, str]]:
    person = await seed_person(session, api, name="Asha")
    headers = {"Authorization": f"Bearer {person.token}"}
    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "gemini", "api_key": "test-key-abcd1234"},
        headers=headers,
    )
    return person.owner_id, headers


async def _agent_row(session: AsyncSession, agent_id: str) -> Agent:
    session.expire_all()
    row = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    assert row is not None
    return row


async def _run_task(task_id: uuid.UUID) -> dict[str, Any]:
    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    return await _execute(get_sessionmaker(), task_id)


# ------------------------------------------------------------------ schedule


async def test_creating_an_agent_with_a_schedule_sets_its_next_run(
    api: AsyncClient, session: AsyncSession
) -> None:
    _, headers = await _person(api, session)
    made = await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)

    assert made.status_code == 201, made.text
    agent = made.json()
    assert agent["schedule_enabled"] is True
    assert agent["schedule_text"] == "Every day at 11:30 PM (Asia/Kolkata)"
    next_run = datetime.fromisoformat(agent["next_run_at"])
    assert next_run > datetime.now(UTC)
    assert next_run - datetime.now(UTC) <= timedelta(days=1, minutes=1)


async def test_a_scheduled_agent_must_list_its_tools(
    api: AsyncClient, session: AsyncSession
) -> None:
    """With no list it would have every tool the person has ever connected."""
    _, headers = await _person(api, session)
    refused = await api.post(AGENTS, json=_new(tools=None, schedule=NIGHTLY), headers=headers)
    assert refused.status_code == 422

    plain = (await api.post(AGENTS, json=_new(tools=None), headers=headers)).json()
    later = await api.patch(f"{AGENTS}/{plain['id']}", json={"schedule": NIGHTLY}, headers=headers)
    assert later.status_code == 422

    scheduled = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()
    widen = await api.patch(f"{AGENTS}/{scheduled['id']}", json={"tools": None}, headers=headers)
    assert widen.status_code == 422


@pytest.mark.parametrize(
    "bad",
    [
        {"frequency": "daily", "time": "25:00"},
        {"frequency": "daily", "time": "23:30", "timezone": "Mars/Base"},
        {"frequency": "weekly", "time": "09:00"},
    ],
)
async def test_a_schedule_that_cannot_run_is_refused(
    api: AsyncClient, session: AsyncSession, bad: dict[str, Any]
) -> None:
    _, headers = await _person(api, session)
    assert (await api.post(AGENTS, json=_new(schedule=bad), headers=headers)).status_code == 422


async def test_pause_resume_and_change_the_time(api: AsyncClient, session: AsyncSession) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()
    url = f"{AGENTS}/{agent['id']}"

    paused = (await api.post(f"{url}/pause", headers=headers)).json()
    assert paused["schedule_enabled"] is False and paused["next_run_at"] is None
    assert paused["schedule"]["time"] == "23:30"  # the time is kept

    resumed = (await api.post(f"{url}/resume", headers=headers)).json()
    assert resumed["schedule_enabled"] is True and resumed["next_run_at"]

    moved = (
        await api.patch(
            url,
            json={"schedule": {"frequency": "weekdays", "time": "06:00", "timezone": "UTC"}},
            headers=headers,
        )
    ).json()
    assert moved["schedule_text"] == "Monday to Friday at 6:00 AM (UTC)"

    cleared = (await api.patch(url, json={"schedule": None}, headers=headers)).json()
    assert cleared["schedule"] is None and cleared["next_run_at"] is None
    assert (await api.post(f"{url}/resume", headers=headers)).status_code == 422


async def test_removing_an_agent_stops_its_schedule(
    api: AsyncClient, session: AsyncSession
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()
    await api.delete(f"{AGENTS}/{agent['id']}", headers=headers)

    row = await _agent_row(session, agent["id"])
    assert row.archived and not row.schedule_enabled and row.next_run_at is None


async def test_the_spreadsheet_limit_is_stored_as_ids(
    api: AsyncClient, session: AsyncSession
) -> None:
    _, headers = await _person(api, session)
    url = f"https://docs.google.com/spreadsheets/d/{SHEET}/edit#gid=0"
    made = await api.post(AGENTS, json=_new(scope={"sheet_ids": [url, SHEET]}), headers=headers)
    assert made.json()["scope"]["sheet_ids"] == [SHEET]

    bad = await api.post(
        AGENTS, json=_new(scope={"sheet_ids": ["https://evil.example/x"]}), headers=headers
    )
    assert bad.status_code == 422


# ------------------------------------------------------------------ Run now


async def test_run_now_starts_a_run_in_the_agents_own_conversation(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()

    started = await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "started"
    assert queued == [uuid.UUID(body["task_id"])]

    task = await session.scalar(select(Task).where(Task.id == uuid.UUID(body["task_id"])))
    assert task is not None and str(task.agent_id) == agent["id"]

    # Its output is kept in a chat of its own, which is in the chat list.
    assert body["conversation_id"]
    listed = (await api.get(CONVERSATIONS, headers=headers)).json()
    assert [c["id"] for c in listed] == [body["conversation_id"]]
    assert listed[0]["title"] == "Night Owl: runs"
    chat = await api.get(f"{CONVERSATIONS}/{body['conversation_id']}", headers=headers)
    assert chat.status_code == 200 and chat.json()["agent_id"] == agent["id"]

    result = await _run_task(task.id)
    assert result["status"] == "completed"

    done = (await api.get(f"{AGENTS}/{agent['id']}", headers=headers)).json()
    assert done["last_status"] == "completed"
    assert done["last_summary"] == "Added 0 events. Nothing to report."
    # Narrowed to its own tool list, and never given the agent builder.
    assert Scripted.seen[0]["tools"] == ["current_time"]
    # Its cost is on the agent, like any other run.
    assert done["usage"]["runs"] == 1


async def test_a_second_run_waits_for_the_first(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()

    assert (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).json()["status"] == (
        "started"
    )
    again = await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)
    assert again.json()["status"] == "busy"
    assert len(queued) == 1


async def test_run_now_does_not_start_when_a_link_is_broken(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    """Google is not connected, so a night of failed calls never begins."""
    _, headers = await _person(api, session)
    agent = (
        await api.post(
            AGENTS,
            json=_new(tools=["sheets_read"], scope={"sheet_ids": [SHEET]}),
            headers=headers,
        )
    ).json()

    result = await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)

    body = result.json()
    assert body["status"] == "needs_attention"
    assert "Google Workspace is not connected" in body["message"]
    assert any(c["fix"] == "connect:google" for c in body["readiness"]["checks"])
    assert queued == []

    shown = (await api.get(f"{AGENTS}/{agent['id']}", headers=headers)).json()
    assert shown["last_status"] == "needs_attention"
    assert "not connected" in shown["last_summary"]


async def test_an_agent_with_no_tools_cannot_be_run_on_its_own(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(tools=None), headers=headers)).json()
    assert (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).status_code == 422


async def test_one_person_cannot_run_or_pause_anothers_agent(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()
    other = await seed_person(session, api)
    theirs = {"Authorization": f"Bearer {other.token}"}

    for action in ("run", "pause", "resume"):
        assert (
            await api.post(f"{AGENTS}/{agent['id']}/{action}", headers=theirs)
        ).status_code == 404
    assert (await api.get(f"{AGENTS}/{agent['id']}/readiness", headers=theirs)).status_code == 404
    assert queued == []


# ------------------------------------------------------- the nightly dispatcher


async def _make_due(session: AsyncSession, agent_id: str) -> None:
    row = await _agent_row(session, agent_id)
    row.next_run_at = datetime.now(UTC) - timedelta(minutes=2)
    await session.commit()


async def test_the_dispatcher_starts_a_due_agent_once_and_moves_it_forward(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    from app.workers.jobs.scheduler import dispatch_due_agents

    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()
    await _make_due(session, agent["id"])

    assert await dispatch_due_agents({}) == 1
    assert len(queued) == 1

    row = await _agent_row(session, agent["id"])
    assert row.next_run_at is not None and row.next_run_at > datetime.now(UTC)
    assert row.last_status == "running"

    # A minute later nothing is due, so it does not fire again.
    assert await dispatch_due_agents({}) == 0
    assert len(queued) == 1


async def test_the_dispatcher_ignores_paused_and_not_yet_due_agents(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    from app.workers.jobs.scheduler import dispatch_due_agents

    _, headers = await _person(api, session)
    soon = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()
    paused = (
        await api.post(AGENTS, json=_new(name="Paused", schedule=NIGHTLY), headers=headers)
    ).json()
    await api.post(f"{AGENTS}/{paused['id']}/pause", headers=headers)
    # Make the paused one's old time look due, to prove the flag is what stops it.
    row = await _agent_row(session, paused["id"])
    row.next_run_at = datetime.now(UTC) - timedelta(minutes=5)
    await session.commit()
    assert soon  # its time is tonight, not now

    assert await dispatch_due_agents({}) == 0
    assert queued == []


async def test_a_run_that_missed_its_time_starts_once_not_once_per_missed_night(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    """The worker was down for three nights: one run when it is back."""
    from app.workers.jobs.scheduler import dispatch_due_agents

    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(schedule=NIGHTLY), headers=headers)).json()
    row = await _agent_row(session, agent["id"])
    row.next_run_at = datetime.now(UTC) - timedelta(days=3)
    await session.commit()

    assert await dispatch_due_agents({}) == 1
    assert await dispatch_due_agents({}) == 0


async def test_the_dispatcher_reports_a_broken_link_instead_of_running(
    api: AsyncClient,
    session: AsyncSession,
    queued: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.notification_service import NotificationService
    from app.workers.jobs.scheduler import dispatch_due_agents

    told: list[tuple[str, str]] = []

    async def record(self: Any, agent: Agent, *, status: str, summary: str) -> None:
        told.append((status, summary))

    monkeypatch.setattr(NotificationService, "agent_run_finished", record)

    _, headers = await _person(api, session)
    agent = (
        await api.post(
            AGENTS,
            json=_new(tools=["sheets_read"], scope={"sheet_ids": [SHEET]}, schedule=NIGHTLY),
            headers=headers,
        )
    ).json()
    await _make_due(session, agent["id"])

    assert await dispatch_due_agents({}) == 0
    assert queued == []
    assert told and told[0][0] == "needs_attention"
    assert "Google Workspace is not connected" in told[0][1]

    row = await _agent_row(session, agent["id"])
    assert row.last_status == "needs_attention"
    # It is not abandoned: tomorrow it tries again.
    assert row.schedule_enabled and row.next_run_at > datetime.now(UTC)


async def test_a_finished_run_tells_the_person(
    api: AsyncClient,
    session: AsyncSession,
    queued: list[uuid.UUID],
    scripted: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.notification_service import NotificationService

    told: list[tuple[str, str]] = []

    async def record(self: Any, agent: Agent, *, status: str, summary: str) -> None:
        told.append((status, summary))

    monkeypatch.setattr(NotificationService, "agent_run_finished", record)

    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    started = (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).json()
    await _run_task(uuid.UUID(started["task_id"]))

    assert told == [("completed", "Added 0 events. Nothing to report.")]


# --------------------------------------------------------- nobody is watching


async def test_an_unattended_run_never_waits_for_an_approval(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    """Writing asks first by default. A run started by the schedule has no
    one to ask, so the tool is refused and no approval is left waiting."""
    from app.services.conversation_service import ConversationService

    owner_id, headers = await _person(api, session)
    agent = (
        await api.post(
            AGENTS,
            json=_new(tools=["sheets_append_rows"], scope={"sheet_ids": [SHEET]}),
            headers=headers,
        )
    ).json()
    # Start it directly, past the readiness check, to prove the second line of defence.
    row = await _agent_row(session, agent["id"])
    conversations = ConversationService(session, owner_id)
    chat = await conversations.create(agent_id=row.id)
    _, task = await conversations.send(chat.id, text="Run your job now.", user_id=owner_id)
    task.agent_id = row.id
    await session.commit()

    Scripted.call_first = "sheets_append_rows"
    result = await _run_task(task.id)

    assert result["status"] == "completed"
    assert (await session.scalars(select(Approval))).all() == []


async def test_a_saved_agent_cannot_write_outside_its_spreadsheet(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    """The limit reaches the tool through the run, not through the prompt."""
    import app.workers.jobs.agent_run as job
    from app.agent.tools import ToolContext  # noqa: F401  (documents what carries it)

    seen: dict[str, Any] = {}
    real = job.AgentLoop

    class Spy(real):  # type: ignore[valid-type, misc]
        def __init__(self, **kwargs: Any) -> None:
            seen["config"] = kwargs["tool_context"].config
            super().__init__(**kwargs)

    job.AgentLoop = Spy  # type: ignore[misc]
    try:
        _, headers = await _person(api, session)
        agent = (
            await api.post(
                AGENTS,
                json=_new(scope={"sheet_ids": [SHEET]}),
                headers=headers,
            )
        ).json()
        started = (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).json()
        await _run_task(uuid.UUID(started["task_id"]))
    finally:
        job.AgentLoop = real  # type: ignore[misc]

    assert seen["config"]["allowed_sheet_ids"] == [SHEET]


async def test_chat_with_an_agent_opens_its_own_chat_where_its_runs_are_kept(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID]
) -> None:
    _, headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()

    first = (await api.post(f"{AGENTS}/{agent['id']}/chat", headers=headers)).json()
    again = (await api.post(f"{AGENTS}/{agent['id']}/chat", headers=headers)).json()
    assert first["conversation_id"] == again["conversation_id"]

    chat = (await api.get(f"{CONVERSATIONS}/{first['conversation_id']}", headers=headers)).json()
    assert chat["agent_id"] == agent["id"]

    # A run goes into the same chat.
    run = (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).json()
    assert run["conversation_id"] == first["conversation_id"]


async def test_an_agent_that_makes_its_own_sheet_keeps_it_for_the_next_run(
    api: AsyncClient,
    session: AsyncSession,
    queued: list[uuid.UUID],
    scripted: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    import httpx

    import app.agent.tools.packs._http as http_mod
    from app.core.crypto import encrypt
    from app.db.models.policy import Connection, ConnectionKind

    owner_id, headers = await _person(api, session)
    g = "https://www.googleapis.com/auth/"
    session.add(
        Connection(
            owner_id=owner_id,
            kind=ConnectionKind.GOOGLE,
            label="a@example.com",
            credential_enc=encrypt(
                json.dumps(
                    {"access_token": "a", "refresh_token": "r", "expires_at": 9_999_999_999}
                ),
                scope=owner_id,
            ),
            credential_last4="r",
            config={"account": "a@example.com", "scopes": [g + "spreadsheets"]},
            status="connected",
            enabled=True,
        )
    )
    await session.commit()
    for effect in ("write",):
        await api.put(
            "/api/v1/me/policies",
            json={
                "scope": "pack",
                "scope_value": "sheets",
                "side_effect": effect,
                "setting": "auto",
            },
            headers=headers,
        )
    monkeypatch.setattr(
        http_mod,
        "_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"spreadsheetId": SHEET})
            )
        ),
    )

    # No spreadsheet is named: it makes its own, and the schedule is still allowed.
    agent = (
        await api.post(
            AGENTS,
            json=_new(tools=["sheets_create", "sheets_append_rows"], schedule=NIGHTLY),
            headers=headers,
        )
    ).json()
    assert (await api.get(f"{AGENTS}/{agent['id']}/readiness", headers=headers)).json()["ok"]

    Scripted.call_first = "sheets_create"
    started = (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).json()
    assert started["status"] == "started", started

    class Maker(Scripted):
        async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
            # The script's first call is sheets_create, with the arguments it needs.
            reply = await super().complete(**kwargs)
            for call in reply.message.tool_calls:
                call.arguments = {"title": "Chennai Events"}
            return reply

    import app.workers.jobs.agent_run as job

    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: Maker(api_key))
    await _run_task(uuid.UUID(started["task_id"]))

    saved = (await api.get(f"{AGENTS}/{agent['id']}", headers=headers)).json()
    assert saved["scope"]["sheet_ids"] == [SHEET]
