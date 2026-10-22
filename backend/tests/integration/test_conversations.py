"""The personal assistant: chats, history, switching AI, and the specialist team."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import pytest
from httpx import AsyncClient
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
from tests.integration.conftest import seed_person

URL = "/api/v1/me/conversations"


class Recorder(LLMProvider):
    """Answers every call, and remembers what each call was sent."""

    provider_key = "gemini"
    calls: ClassVar[list[dict[str, Any]]] = []

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        Recorder.calls.append(
            {**kwargs, "messages": list(kwargs["messages"]), "provider": self.api_key}
        )
        last_user = next(m.content for m in reversed(kwargs["messages"]) if m.role is Role.USER)
        return LLMReply(
            message=Message(role=Role.ASSISTANT, content=f"Answer to: {last_user}"),
            stop_reason=StopReason.END_TURN,
            usage=Usage(100, 20),
            model=kwargs["model"],
        )

    async def check(self, model: str) -> None:
        return None


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> type[Recorder]:
    import app.workers.jobs.agent_run as job

    Recorder.calls = []
    # The "api key" doubles as the provider's name, so a test can see
    # which provider answered.
    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: Recorder(key))
    return Recorder


async def _person(api: AsyncClient, session: AsyncSession, *providers: str) -> dict[str, str]:
    person = await seed_person(session, api, name="Asha")
    headers = {"Authorization": f"Bearer {person.token}"}
    for key in providers or ("gemini",):
        await api.post(
            "/api/v1/me/providers",
            json={"provider_key": key, "api_key": f"{key}-test-key-1234"},
            headers=headers,
        )
    return headers


async def _run(task_id: str) -> dict[str, Any]:
    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    return await _execute(get_sessionmaker(), uuid.UUID(task_id))


async def _say(api: AsyncClient, headers: dict[str, str], cid: str, text: str) -> dict[str, Any]:
    sent = await api.post(f"{URL}/{cid}/messages", json={"content": text}, headers=headers)
    assert sent.status_code == 202, sent.text
    await _run(sent.json()["task_id"])
    return (await api.get(f"{URL}/{cid}", headers=headers)).json()


async def test_a_chat_remembers_the_conversation(
    api: AsyncClient, session: AsyncSession, recorder: type[Recorder]
) -> None:
    headers = await _person(api, session)
    created = await api.post(URL, json={"mode": "study"}, headers=headers)
    assert created.status_code == 201
    cid = created.json()["id"]

    first = await _say(api, headers, cid, "Teach me recursion")
    assert first["title"] == "Teach me recursion"
    assert [m["role"] for m in first["messages"]] == ["user", "assistant"]
    assert first["messages"][1]["content"] == "Answer to: Teach me recursion"
    assert first["messages"][1]["model"].startswith("gemini:")
    assert first["turn"]["status"] == "completed"

    await _say(api, headers, cid, "Now give me an exercise")
    second_call = recorder.calls[-1]["messages"]
    # Instructions, then the earlier exchange, then the new message.
    assert second_call[0].role is Role.SYSTEM
    assert "tutor" in (second_call[0].content or "")
    assert [(m.role, m.content) for m in second_call[1:]] == [
        (Role.USER, "Teach me recursion"),
        (Role.ASSISTANT, "Answer to: Teach me recursion"),
        (Role.USER, "Now give me an exercise"),
    ]

    # Every turn is a task, and the task list is how the activity
    # count and the notification bell find them. (They used to be kept
    # out of it, back when the list belonged to AI Employees.)
    listed = (await api.get("/api/v1/me/tasks", headers=headers)).json()
    assert len(listed) == 2
    assert {t["conversation_id"] for t in listed} == {cid}


async def test_one_answer_at_a_time(
    api: AsyncClient, session: AsyncSession, recorder: type[Recorder]
) -> None:
    headers = await _person(api, session)
    cid = (await api.post(URL, json={}, headers=headers)).json()["id"]

    await api.post(f"{URL}/{cid}/messages", json={"content": "One"}, headers=headers)
    again = await api.post(f"{URL}/{cid}/messages", json={"content": "Two"}, headers=headers)
    assert again.status_code == 422
    assert "Wait for the current answer" in again.json()["detail"]


async def test_switching_the_ai_mid_conversation(
    api: AsyncClient, session: AsyncSession, recorder: type[Recorder]
) -> None:
    headers = await _person(api, session, "gemini", "groq")
    cid = (await api.post(URL, json={"model": "gemini:gemini-2.5-flash"}, headers=headers)).json()[
        "id"
    ]
    await _say(api, headers, cid, "Hello")

    switched = await api.patch(
        f"{URL}/{cid}", json={"model": "groq:llama-3.3-70b"}, headers=headers
    )
    assert switched.status_code == 200
    after = await _say(api, headers, cid, "Still there?")

    assert [c["provider"] for c in recorder.calls] == ["gemini", "groq"]
    assert [m["model"] for m in after["messages"] if m["role"] == "assistant"] == [
        "gemini:gemini-2.5-flash",
        "groq:llama-3.3-70b",
    ]
    # The new AI still sees what the old one said.
    assert any(m.content == "Answer to: Hello" for m in recorder.calls[-1]["messages"])

    not_connected = await api.patch(
        f"{URL}/{cid}", json={"model": "anthropic:claude-opus-5-5"}, headers=headers
    )
    assert not_connected.status_code == 422


async def test_a_failed_reply_is_said_plainly_and_kept_out_of_history(
    api: AsyncClient, session: AsyncSession, recorder: type[Recorder]
) -> None:
    person = await seed_person(session, api, name="Ravi")
    headers = {"Authorization": f"Bearer {person.token}"}  # no AI connected
    cid = (await api.post(URL, json={}, headers=headers)).json()["id"]

    failed = await _say(api, headers, cid, "Hi")
    reply = failed["messages"][1]
    assert reply["role"] == "assistant"
    assert "No AI key is connected" in reply["error"]

    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "gemini", "api_key": "gemini-test-key-1234"},
        headers=headers,
    )
    await _say(api, headers, cid, "Hi again")
    sent = recorder.calls[-1]["messages"]
    assert not any("No AI key is connected" in (m.content or "") for m in sent)


async def test_another_person_cannot_read_a_conversation(
    api: AsyncClient, session: AsyncSession
) -> None:
    owner = await _person(api, session)
    cid = (await api.post(URL, json={}, headers=owner)).json()["id"]

    other = await seed_person(session, api, name="Someone else")
    other_headers = {"Authorization": f"Bearer {other.token}"}
    assert (await api.get(f"{URL}/{cid}", headers=other_headers)).status_code == 404
    assert (await api.get(URL, headers=other_headers)).json() == []
    sent = await api.post(f"{URL}/{cid}/messages", json={"content": "x"}, headers=other_headers)
    assert sent.status_code == 404


async def test_every_tool_the_person_can_use_is_on_without_picking(
    api: AsyncClient, session: AsyncSession, recorder: type[Recorder]
) -> None:
    """Tools are the platform's side: nothing to tick. Built-in tools are
    on, an app's tools wait for that app to be connected, and a tool the
    person's Permissions block is not offered at all."""
    headers = await _person(api, session)
    cid = (await api.post(URL, json={"mode": "research"}, headers=headers)).json()["id"]
    await _say(api, headers, cid, "Hello")

    offered = {t.name for t in recorder.calls[-1]["tools"]}
    assert {"get_webpage", "recall", "remember"} <= offered
    assert "gmail_send" not in offered  # Google is not connected
    assert "delegate_to_specialist" not in offered  # that is for AI Employees

    blocked = await api.put(
        "/api/v1/me/policies",
        json={"scope": "pack", "scope_value": "web", "side_effect": "read", "setting": "blocked"},
        headers=headers,
    )
    assert blocked.status_code == 200, blocked.text
    await _say(api, headers, cid, "Again")
    assert "get_webpage" not in {t.name for t in recorder.calls[-1]["tools"]}

    info = (await api.get("/api/v1/me/assistant", headers=headers)).json()
    assert [m["key"] for m in info["modes"]] == ["general", "study", "work", "research", "code"]
    assert {r["key"] for r in info["team_roles"]} == {
        "researcher",
        "analyst",
        "writer",
        "critic",
        "developer",
        "generalist",
    }
    assert "suggested_tools" not in info["modes"][0]


async def test_team_mode_runs_specialists_in_parallel_and_combines_them(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Orchestration: the lead fans out to two specialists in one step,
    they run at the same time, and the lead combines their answers."""
    import app.workers.jobs.agent_run as job

    seen: list[str] = []

    class TeamPlay(LLMProvider):
        provider_key = "gemini"

        async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
            messages: list[Message] = kwargs["messages"]
            system = messages[0].content or ""
            tools = {t.name for t in kwargs.get("tools") or []}

            if system.startswith("You are a researcher"):
                seen.append("researcher")
                assert "ask_specialist" not in tools  # depth 1: no chains
                text = "Finding: four-day weeks kept output steady in trials."
            elif system.startswith("You are a critic"):
                seen.append("critic")
                text = "Check: the trials were small; say so."
            elif not any(m.role is Role.TOOL for m in messages):
                seen.append("lead-plan")
                assert "ask_specialist" in tools
                return LLMReply(
                    message=Message(
                        role=Role.ASSISTANT,
                        tool_calls=[
                            ToolCall(
                                "a",
                                "ask_specialist",
                                {"role": "researcher", "task": "Find trial results"},
                            ),
                            ToolCall(
                                "b",
                                "ask_specialist",
                                {"role": "critic", "task": "What are the caveats?"},
                            ),
                        ],
                    ),
                    stop_reason=StopReason.TOOL_USE,
                    usage=Usage(200, 40),
                    model=kwargs["model"],
                )
            else:
                seen.append("lead-combine")
                results = " | ".join(m.content or "" for m in messages if m.role is Role.TOOL)
                text = f"Combined: {results}"
            return LLMReply(
                message=Message(role=Role.ASSISTANT, content=text),
                stop_reason=StopReason.END_TURN,
                usage=Usage(100, 20),
                model=kwargs["model"],
            )

        async def check(self, model: str) -> None:
            return None

    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: TeamPlay(api_key))
    headers = await _person(api, session)
    cid = (await api.post(URL, json={"mode": "research", "team": True}, headers=headers)).json()[
        "id"
    ]

    done = await _say(api, headers, cid, "Is a four-day work week a good idea?")
    reply = done["messages"][1]["content"]
    # The reply says who worked on it, without loading the run.
    assert sorted(done["messages"][1]["tools_used"]) == [
        "specialist:critic",
        "specialist:researcher",
    ]
    assert "four-day weeks kept output steady" in reply
    assert "the trials were small" in reply
    assert seen[0] == "lead-plan" and seen[-1] == "lead-combine"
    assert sorted(seen[1:3]) == ["critic", "researcher"]

    trace = (
        await api.get(f"/api/v1/me/runs/{done['turn']['run_id']}/trace", headers=headers)
    ).json()["events"]
    types = [e["type"] for e in trace]
    assert "parallel_started" in types
    assert types.count("specialist_started") == 2
    assert types.count("specialist_finished") == 2

    task = (await api.get(f"/api/v1/me/tasks/{done['turn']['task_id']}", headers=headers)).json()
    # Lead (2 calls) and both specialists are all counted.
    assert task["run"]["prompt_tokens"] == 200 + 100 + 100 + 100


async def test_supervised_team_mode_routes_runs_helpers_and_combines_them(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the supervisor on, a router picks the helpers, they work, and the
    lead answers from what they found. The lead is not offered
    `ask_specialist`, because the graph already did that part."""
    import json
    from types import SimpleNamespace

    import app.workers.jobs.agent_run as job
    from app.agent.supervisor import ROUTER_PROMPT

    seen: list[str] = []
    lead_tools: list[set[str]] = []

    class Supervised(LLMProvider):
        provider_key = "gemini"

        async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
            messages: list[Message] = kwargs["messages"]
            system = messages[0].content or ""
            if system == ROUTER_PROMPT:
                seen.append("router")
                text = json.dumps(
                    {
                        "helpers": [{"role": "researcher", "task": "Find trial results"}],
                        "report": False,
                    }
                )
            elif system.startswith("You are a researcher"):
                seen.append("researcher")
                text = "Finding: four-day weeks kept output steady."
            else:
                seen.append("lead")
                lead_tools.append({t.name for t in kwargs.get("tools") or []})
                text = f"Answer from the team: {messages[-1].content}"
            return LLMReply(
                message=Message(role=Role.ASSISTANT, content=text),
                stop_reason=StopReason.END_TURN,
                usage=Usage(100, 20),
                model=kwargs["model"],
            )

        async def check(self, model: str) -> None:
            return None

    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: Supervised(api_key))
    monkeypatch.setattr(job, "get_settings", lambda: SimpleNamespace(agent_supervisor=True))
    headers = await _person(api, session)
    cid = (await api.post(URL, json={"mode": "research", "team": True}, headers=headers)).json()[
        "id"
    ]

    done = await _say(api, headers, cid, "Is a four-day work week a good idea?")
    reply = done["messages"][1]["content"]
    assert "four-day weeks kept output steady" in reply
    assert seen == ["router", "researcher", "lead"]
    assert "ask_specialist" not in lead_tools[0]
    assert done["messages"][1]["tools_used"] == ["specialist:researcher"]

    trace = (
        await api.get(f"/api/v1/me/runs/{done['turn']['run_id']}/trace", headers=headers)
    ).json()["events"]
    types = [e["type"] for e in trace]
    assert "supervisor_plan" in types
    assert types.count("specialist_started") == 1
    assert types.count("specialist_finished") == 1

    task = (await api.get(f"/api/v1/me/tasks/{done['turn']['task_id']}", headers=headers)).json()
    # Router, researcher and lead are all counted.
    assert task["run"]["prompt_tokens"] == 300


async def test_with_team_mode_off_there_is_no_specialist_tool(
    api: AsyncClient, session: AsyncSession, recorder: type[Recorder]
) -> None:
    headers = await _person(api, session)
    cid = (await api.post(URL, json={"team": False}, headers=headers)).json()["id"]
    await _say(api, headers, cid, "Hi")
    tools = {t.name for t in recorder.calls[-1].get("tools") or []}
    assert "ask_specialist" not in tools


async def test_an_unreadable_saved_key_is_explained_not_left_hanging(
    api: AsyncClient, session: AsyncSession, recorder: type[Recorder]
) -> None:
    """A key saved under another scope (as companies' keys were before
    personal accounts) used to crash the worker and leave the chat
    waiting for ever. It now ends the turn with what to do."""
    from sqlalchemy import update

    from app.core.crypto import encrypt
    from app.db.models.provider import ProviderConfig

    headers = await _person(api, session)
    await session.execute(
        update(ProviderConfig).values(api_key_enc=encrypt("old-key", scope=uuid.uuid4()))
    )
    await session.commit()
    cid = (await api.post(URL, json={}, headers=headers)).json()["id"]

    done = await _say(api, headers, cid, "Hello")
    assert done["turn"]["status"] == "failed"
    assert "can no longer be read" in done["messages"][1]["error"]
    assert recorder.calls == []
