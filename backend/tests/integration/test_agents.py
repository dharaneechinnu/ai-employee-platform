"""Agents: made by talking, owned by one person, never wider than Permissions.

The model is stubbed, because what is being tested is the platform around
it: that designing an agent in Chat can only show a draft, that nothing
exists until the person creates it, and that an agent narrows a chat and
never widens it.
"""

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

AGENTS = "/api/v1/me/agents"
CONVERSATIONS = "/api/v1/me/conversations"

DRAFT = {
    "name": "Friday Digest",
    "description": "Summarises the week's newsletters every Friday.",
    "instructions": "You are a digest writer. Summarise what you are given in five bullets.",
    "tools": ["fetch_url"],
}


class Scripted(LLMProvider):
    """Records what it was sent; the builder script calls `propose_agent` once."""

    provider_key = "gemini"
    seen: ClassVar[list[dict[str, Any]]] = []

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        messages: list[Message] = kwargs["messages"]
        tools = [t.name for t in kwargs.get("tools") or []]
        Scripted.seen.append({"system": messages[0].content, "tools": tools})
        proposing = "propose_agent" in tools and not any(m.role is Role.TOOL for m in messages)
        if proposing:
            reply = Message(
                role=Role.ASSISTANT,
                content=None,
                tool_calls=[ToolCall(id="c1", name="propose_agent", arguments=DRAFT)],
            )
            stop = StopReason.TOOL_USE
        else:
            reply = Message(role=Role.ASSISTANT, content="Here you go.")
            stop = StopReason.END_TURN
        return LLMReply(
            message=reply,
            stop_reason=stop,
            usage=Usage(prompt_tokens=100, output_tokens=20),
            model="gemini-2.0-flash",
            latency_ms=5,
        )

    async def check(self, model: str) -> None:
        return None


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.workers.jobs.agent_run as job

    Scripted.seen = []
    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: Scripted(api_key))


async def _person(api: AsyncClient, session: AsyncSession) -> dict[str, str]:
    person = await seed_person(session, api, name="Asha")
    headers = {"Authorization": f"Bearer {person.token}"}
    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "gemini", "api_key": "test-key-abcd1234"},
        headers=headers,
    )
    return headers


async def _say(api: AsyncClient, headers: dict[str, str], cid: str, text: str) -> str:
    sent = await api.post(
        f"{CONVERSATIONS}/{cid}/messages", json={"content": text}, headers=headers
    )
    assert sent.status_code == 202, sent.text
    return str(sent.json()["task_id"])


async def _run(task_id: str) -> dict[str, Any]:
    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    return await _execute(get_sessionmaker(), uuid.UUID(task_id))


def _new(**over: Any) -> dict[str, Any]:
    return {
        "name": "Tutor",
        "description": "Explains things.",
        "instructions": "You are a patient maths tutor. Use small steps.",
        **over,
    }


async def test_create_change_and_remove_an_agent(api: AsyncClient, session: AsyncSession) -> None:
    headers = await _person(api, session)

    made = await api.post(AGENTS, json=_new(), headers=headers)
    assert made.status_code == 201, made.text
    agent = made.json()
    assert agent["handle"] == "tutor"

    # A second one with the same name gets its own handle.
    again = await api.post(AGENTS, json=_new(), headers=headers)
    assert again.json()["handle"] == "tutor-2"

    changed = await api.patch(
        f"{AGENTS}/{agent['id']}", json={"description": "Maths only."}, headers=headers
    )
    assert changed.json()["description"] == "Maths only."

    overview = await api.get(f"{AGENTS}/overview", headers=headers)
    assert [a["name"] for a in overview.json()["agents"]] == ["Tutor", "Tutor"]
    # The five modes and four specialists are the starters.
    assert len(overview.json()["starters"]) == 11

    assert (await api.delete(f"{AGENTS}/{agent['id']}", headers=headers)).status_code == 204
    after = await api.get(f"{AGENTS}/overview", headers=headers)
    assert len(after.json()["agents"]) == 1
    assert (await api.get(f"{AGENTS}/{agent['id']}", headers=headers)).json()["name"] == "Tutor"


async def test_an_agent_cannot_be_given_the_builders_or_the_teams_tool(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Agents making agents, or calling each other, is how one poisoned
    page becomes a swarm."""
    headers = await _person(api, session)
    for tool in ("propose_agent", "ask_specialist"):
        refused = await api.post(AGENTS, json=_new(tools=[tool]), headers=headers)
        assert refused.status_code == 422


async def test_one_person_cannot_see_or_change_anothers_agent(
    api: AsyncClient, session: AsyncSession
) -> None:
    headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()

    other = await seed_person(session, api)
    theirs = {"Authorization": f"Bearer {other.token}"}

    assert (await api.get(f"{AGENTS}/{agent['id']}", headers=theirs)).status_code == 404
    patch = await api.patch(f"{AGENTS}/{agent['id']}", json={"name": "Mine now"}, headers=theirs)
    assert patch.status_code == 404
    assert (await api.delete(f"{AGENTS}/{agent['id']}", headers=theirs)).status_code == 404
    assert (await api.get(f"{AGENTS}/overview", headers=theirs)).json()["agents"] == []
    # And they cannot start a chat as it.
    chat = await api.post(CONVERSATIONS, json={"agent_id": agent["id"]}, headers=theirs)
    assert chat.status_code == 404


async def test_chat_shows_a_draft_when_asked_for_an_agent_and_creates_nothing(
    api: AsyncClient, session: AsyncSession, scripted: None
) -> None:
    headers = await _person(api, session)
    chat = await api.post(CONVERSATIONS, json={}, headers=headers)
    cid = chat.json()["id"]

    task_id = await _say(api, headers, cid, "Make me an agent that writes a Friday digest")
    assert (await _run(task_id))["status"] == "completed"

    # The ordinary chat gains one tool, and keeps its others.
    offered = Scripted.seen[0]["tools"]
    assert "propose_agent" in offered
    assert "get_webpage" in offered
    # The builder's steps and the tool list reached the model.
    assert "ASK FIRST" in Scripted.seen[0]["system"]
    assert "sheets_append_rows" in Scripted.seen[0]["system"]

    messages = (await api.get(f"{CONVERSATIONS}/{cid}", headers=headers)).json()["messages"]
    reply = messages[-1]
    assert reply["draft"]["name"] == "Friday Digest"
    assert reply["draft"]["schedule"] is None

    # Showing it created nothing. It is an ordinary chat, so it is in the list.
    assert (await api.get(f"{AGENTS}/overview", headers=headers)).json()["agents"] == []
    assert len((await api.get(CONVERSATIONS, headers=headers)).json()) == 1

    # Pressing Create is what makes it.
    made = await api.post(AGENTS, json=reply["draft"], headers=headers)
    assert made.status_code == 201, made.text
    assert made.json()["tools"] == ["fetch_url"]


async def test_chat_that_is_not_about_agents_is_left_alone(
    api: AsyncClient, session: AsyncSession, scripted: None
) -> None:
    headers = await _person(api, session)
    chat = await api.post(CONVERSATIONS, json={}, headers=headers)
    await _run(await _say(api, headers, chat.json()["id"], "What is a mutual fund SIP?"))

    assert "propose_agent" not in Scripted.seen[0]["tools"]
    assert "ASK FIRST" not in Scripted.seen[0]["system"]


async def test_a_saved_agent_cannot_design_another(
    api: AsyncClient, session: AsyncSession, scripted: None
) -> None:
    headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    chat = await api.post(CONVERSATIONS, json={"agent_id": agent["id"]}, headers=headers)
    await _run(await _say(api, headers, chat.json()["id"], "Make me an agent that sends mail"))

    assert "propose_agent" not in Scripted.seen[0]["tools"]


async def test_a_chat_with_an_agent_uses_its_instructions_and_only_its_tools(
    api: AsyncClient, session: AsyncSession, scripted: None
) -> None:
    headers = await _person(api, session)
    agent = (
        await api.post(AGENTS, json=_new(tools=["recall"], name="Memory Tutor"), headers=headers)
    ).json()
    chat = await api.post(CONVERSATIONS, json={"agent_id": agent["id"]}, headers=headers)
    assert chat.json()["agent_id"] == agent["id"]

    task_id = await _say(api, headers, chat.json()["id"], "Teach me fractions")
    assert (await _run(task_id))["status"] == "completed"

    sent = Scripted.seen[0]
    assert "patient maths tutor" in sent["system"]
    assert "Memory Tutor" in sent["system"]
    # Narrowed to the one tool; nothing wider is offered.
    assert sent["tools"] == ["recall"]


async def test_cost_is_counted_per_agent(
    api: AsyncClient, session: AsyncSession, scripted: None
) -> None:
    headers = await _person(api, session)
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    chat = await api.post(CONVERSATIONS, json={"agent_id": agent["id"]}, headers=headers)
    await _run(await _say(api, headers, chat.json()["id"], "Teach me fractions"))

    plain = await api.post(CONVERSATIONS, json={}, headers=headers)
    await _run(await _say(api, headers, plain.json()["id"], "Hello"))

    overview = (await api.get(f"{AGENTS}/overview", headers=headers)).json()
    assert overview["agents"][0]["usage"]["runs"] == 1
    assert overview["agents"][0]["usage"]["prompt_tokens"] == 100
    # Chats with no agent are the plain assistant's.
    assert overview["assistant_usage"]["runs"] == 1
    assert len(overview["recent_runs"]) == 2
