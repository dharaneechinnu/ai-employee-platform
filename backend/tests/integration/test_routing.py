"""Automatic routing end to end: the right connected AI per task, with fallback."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    ProviderRateLimitError,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from app.agent.routing import CLASSIFY_PROMPT
from tests.integration.conftest import seed_person

URL = "/api/v1/me/conversations"
SPECIALISTS = ("You are a researcher", "You are an analyst", "You are a writer", "You are a critic")


class World:
    """Stub AIs, one per provider. Records who answered what; any
    provider listed in `down` is rate-limited."""

    def __init__(self) -> None:
        self.answered: list[tuple[str, str]] = []
        self.down: set[str] = set()
        self.classify_answer = "general"
        self.classified_by: list[str] = []

    def build(self, key: str, api_key: str, **_: Any) -> LLMProvider:
        world = self

        class Stub(LLMProvider):
            provider_key = key

            async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
                messages: list[Message] = kwargs["messages"]
                system = messages[0].content or ""
                if system == CLASSIFY_PROMPT:
                    world.classified_by.append(key)
                    return _reply(world.classify_answer, kwargs["model"])
                if key in world.down:
                    raise ProviderRateLimitError(f"{key} is busy")
                world.answered.append((key, kwargs["model"]))
                if system.startswith(SPECIALISTS):
                    return _reply(f"{key} specialist notes", kwargs["model"])
                if (
                    kwargs.get("tools")
                    and any(t.name == "ask_specialist" for t in kwargs["tools"])
                    and not any(m.role is Role.TOOL for m in messages)
                ):
                    return LLMReply(
                        message=Message(
                            role=Role.ASSISTANT,
                            tool_calls=[
                                ToolCall(
                                    "a", "ask_specialist", {"role": "researcher", "task": "Read"}
                                ),
                                ToolCall(
                                    "b", "ask_specialist", {"role": "analyst", "task": "Think"}
                                ),
                            ],
                        ),
                        stop_reason=StopReason.TOOL_USE,
                        usage=Usage(10, 5),
                        model=kwargs["model"],
                    )
                return _reply(f"answered by {key}", kwargs["model"])

            async def check(self, model: str) -> None:
                return None

        return Stub(api_key)


def _reply(text: str, model: str) -> LLMReply:
    return LLMReply(
        message=Message(role=Role.ASSISTANT, content=text),
        stop_reason=StopReason.END_TURN,
        usage=Usage(10, 5),
        model=model,
    )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    import app.workers.jobs.agent_run as job

    w = World()
    monkeypatch.setattr(job, "build_provider", w.build)
    return w


async def _person(api: AsyncClient, session: AsyncSession, *providers: str) -> dict[str, str]:
    person = await seed_person(session, api, name="Meera")
    headers = {"Authorization": f"Bearer {person.token}"}
    for key in providers:
        body: dict[str, Any] = {"provider_key": key, "api_key": f"{key}-test-key-1234"}
        if key == "custom":
            body |= {"base_url": "https://llm.example.com/v1", "model": "llama-3.3-70b"}
        response = await api.post("/api/v1/me/providers", json=body, headers=headers)
        assert response.status_code == 201, response.text
    return headers


async def _ask(
    api: AsyncClient, headers: dict[str, str], text: str, **settings: Any
) -> dict[str, Any]:
    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    cid = (await api.post(URL, json=settings, headers=headers)).json()["id"]
    sent = await api.post(f"{URL}/{cid}/messages", json={"content": text}, headers=headers)
    await _execute(get_sessionmaker(), uuid.UUID(sent.json()["task_id"]))
    convo = (await api.get(f"{URL}/{cid}", headers=headers)).json()
    return convo["messages"][-1] | {"turn": convo["turn"]}


async def test_automatic_picks_the_best_connected_ai_for_each_task(
    api: AsyncClient, session: AsyncSession, world: World
) -> None:
    headers = await _person(api, session, "anthropic", "gemini")

    coding = await _ask(api, headers, "Fix this ```python\nprint(x)``` NameError")
    assert coding["model"] == "anthropic:claude-opus-5-5"
    assert "coding" in coding["model_reason"]

    quick = await _ask(api, headers, "What is the capital of Peru?")
    assert quick["model"].startswith("gemini:")
    assert "quick question" in quick["model_reason"]

    # Rules were enough both times: no classification call was made.
    assert world.classified_by == []


async def test_best_quality_and_lowest_cost_change_the_choice(
    api: AsyncClient, session: AsyncSession, world: World
) -> None:
    headers = await _person(api, session, "anthropic", "gemini")
    best = await _ask(api, headers, "What is the capital of Peru?", routing="quality")
    cheap = await _ask(api, headers, "Compare two job offers: pros and cons", routing="cost")
    assert best["model"].startswith("anthropic:")
    assert cheap["model"].startswith("gemini:")


async def test_an_unclear_task_is_classified_by_the_cheapest_ai(
    api: AsyncClient, session: AsyncSession, world: World
) -> None:
    headers = await _person(api, session, "anthropic", "gemini")
    world.classify_answer = "analysis"
    reply = await _ask(api, headers, "Thoughts on my weekend?")
    assert world.classified_by == ["gemini"]  # one tiny call, to the cheap one
    assert reply["model"].startswith("anthropic:")  # analysis is hard work


async def test_a_busy_ai_hands_over_to_the_next_best(
    api: AsyncClient, session: AsyncSession, world: World
) -> None:
    headers = await _person(api, session, "anthropic", "gemini")
    world.down = {"anthropic"}
    reply = await _ask(api, headers, "Fix this ```python\nprint(x)```")

    assert reply["error"] is None
    assert reply["content"] == "answered by gemini"
    assert reply["model"].startswith("gemini:")
    assert "unavailable" in reply["model_reason"]

    run_id = reply["turn"]["run_id"]
    trace = (await api.get(f"/api/v1/me/runs/{run_id}/trace", headers=headers)).json()
    kinds = [e["type"] for e in trace["events"]]
    assert kinds[0] == "model_chosen"
    assert "model_fallback" in kinds


async def test_a_pinned_ai_is_used_as_chosen(
    api: AsyncClient, session: AsyncSession, world: World
) -> None:
    headers = await _person(api, session, "anthropic", "gemini")
    reply = await _ask(
        api, headers, "Fix this ```python\nprint(x)```", model="gemini:gemini-2.0-flash"
    )
    assert reply["model"] == "gemini:gemini-2.0-flash"
    assert reply["model_reason"] == "the AI you chose"


async def test_private_only_needs_your_own_server(
    api: AsyncClient, session: AsyncSession, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.urls as urls

    monkeypatch.setattr(urls, "is_private_address", lambda host: False)
    headers = await _person(api, session, "anthropic")
    refused = await _ask(api, headers, "Summarise my notes", routing="private")
    assert "Private only" in refused["error"]

    await api.post(
        "/api/v1/me/providers",
        json={
            "provider_key": "custom",
            "base_url": "https://llm.example.com/v1",
            "model": "llama-3.3-70b",
        },
        headers=headers,
    )
    private = await _ask(api, headers, "Fix this ```python\nprint(x)```", routing="private")
    assert private["model"] == "custom:llama-3.3-70b"
    assert world.answered[-1][0] == "custom"


async def test_each_specialist_gets_the_ai_best_for_its_role(
    api: AsyncClient, session: AsyncSession, world: World
) -> None:
    headers = await _person(api, session, "anthropic", "gemini")
    reply = await _ask(api, headers, "Compare remote and office work: pros and cons", team=True)
    trace = (
        await api.get(f"/api/v1/me/runs/{reply['turn']['run_id']}/trace", headers=headers)
    ).json()
    started = {
        e["payload"]["role"]: e["payload"]["model"]
        for e in trace["events"]
        if e["type"] == "specialist_started"
    }
    assert started["researcher"].startswith("gemini:")  # long reading
    assert started["analyst"].startswith("anthropic:")  # careful reasoning


async def test_the_providers_page_says_what_each_ai_is_good_at(
    api: AsyncClient, session: AsyncSession
) -> None:
    headers = await _person(api, session, "anthropic", "groq")
    connected = {
        p["provider_key"]: p["strengths"]
        for p in (await api.get("/api/v1/me/providers", headers=headers)).json()
    }
    assert "coding" in connected["anthropic"]
    assert "very fast" in connected["groq"]
