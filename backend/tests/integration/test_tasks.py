"""Turns as tasks: run, trace, cancel, list, and who may see them.

Every reply the assistant gives is a task, and the task routes are how
the activity count, the notification bell and the run trace find them.
These tests cover that surface; what is *said* in a conversation lives
in test_conversations.

The worker job is executed directly rather than through Redis. That
keeps the test fast and deterministic while still exercising the real
code path — the same function arq calls in production. The provider is
stubbed, because a real model gives a different answer every time and
costs money and rate limit on every CI run.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.providers.base import LLMProvider, LLMReply, Message, Role, StopReason, Usage
from tests.integration.conftest import seed_person

CONVERSATIONS = "/api/v1/me/conversations"


class StubProvider(LLMProvider):
    """Answers immediately, with no tool calls."""

    provider_key = "gemini"

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        return LLMReply(
            message=Message(role=Role.ASSISTANT, content="The bug is on line 24."),
            stop_reason=StopReason.END_TURN,
            usage=Usage(prompt_tokens=120, output_tokens=30),
            model="gemini-2.0-flash",
            latency_ms=42,
        )

    async def check(self, model: str) -> None:
        return None


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.workers.jobs.agent_run as job

    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: StubProvider(api_key))


async def _person(api: AsyncClient, session: AsyncSession) -> dict[str, str]:
    """Somebody with a connected AI, ready to chat."""
    person = await seed_person(session, api, name="Asha")
    headers = {"Authorization": f"Bearer {person.token}"}
    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "gemini", "api_key": "test-key-abcd1234"},
        headers=headers,
    )
    return headers


async def _send(api: AsyncClient, headers: dict[str, str], text: str) -> str:
    """Start a conversation, say something, and return the turn's task id.

    The job is queued but not run: the caller decides whether the
    worker gets to it, which is the whole point of the cancel tests.
    """
    created = await api.post(CONVERSATIONS, json={"mode": "study"}, headers=headers)
    cid = created.json()["id"]
    sent = await api.post(
        f"{CONVERSATIONS}/{cid}/messages", json={"content": text}, headers=headers
    )
    assert sent.status_code == 202, sent.text
    return str(sent.json()["task_id"])


async def _run(task_id: str) -> dict[str, Any]:
    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    return await _execute(get_sessionmaker(), uuid.UUID(task_id))


async def test_the_worker_runs_the_turn_and_records_the_result(
    api: AsyncClient, session: AsyncSession, stub_provider: None
) -> None:
    headers = await _person(api, session)
    task_id = await _send(api, headers, "Look at bug 42")

    assert (await _run(task_id))["status"] == "completed"

    task = await api.get(f"/api/v1/me/tasks/{task_id}", headers=headers)
    assert task.json()["status"] == "completed"
    run = task.json()["run"]
    assert run["output"] == "The bug is on line 24."
    assert run["prompt_tokens"] == 120
    assert run["output_tokens"] == 30


async def test_the_run_trace_records_every_step(
    api: AsyncClient, session: AsyncSession, stub_provider: None
) -> None:
    """The event log is what makes a run debuggable and auditable."""
    headers = await _person(api, session)
    task_id = await _send(api, headers, "Look at bug 42")
    await _run(task_id)

    task = await api.get(f"/api/v1/me/tasks/{task_id}", headers=headers)
    run_id = task.json()["run"]["id"]

    trace = await api.get(f"/api/v1/me/runs/{run_id}/trace", headers=headers)
    events = trace.json()["events"]

    # First, which AI was chosen and why; then the run itself.
    assert [e["type"] for e in events][:3] == ["model_chosen", "run_started", "thinking"]
    assert events[0]["payload"]["reason"]
    # seq is gap-free, which is what lets a reconnecting client resume.
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert trace.json()["llm_calls"][0]["prompt_tokens"] == 120


async def test_cancelling_a_queued_turn(api: AsyncClient, session: AsyncSession) -> None:
    headers = await _person(api, session)
    task_id = await _send(api, headers, "Look at bug 42")

    cancelled = await api.post(f"/api/v1/me/tasks/{task_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


async def test_a_cancelled_turn_is_not_run_by_the_worker(
    api: AsyncClient, session: AsyncSession, stub_provider: None
) -> None:
    headers = await _person(api, session)
    task_id = await _send(api, headers, "Look at bug 42")
    await api.post(f"/api/v1/me/tasks/{task_id}/cancel", headers=headers)

    # The worker sees it is no longer queued and does not run it.
    assert (await _run(task_id))["status"] == "cancelled"


async def test_turns_appear_in_the_task_list(api: AsyncClient, session: AsyncSession) -> None:
    headers = await _person(api, session)
    await _send(api, headers, "first")

    listed = await api.get("/api/v1/me/tasks", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    # The list says which conversation each one belongs to, so the
    # notification bell can link straight to it.
    assert listed.json()[0]["conversation_id"]


async def test_one_person_cannot_read_or_cancel_anothers_task(
    api: AsyncClient, session: AsyncSession
) -> None:
    headers = await _person(api, session)
    task_id = await _send(api, headers, "secret work")

    other = await seed_person(session, api)
    theirs = {"Authorization": f"Bearer {other.token}"}

    # 404, not 403: whether somebody else's task exists is not theirs
    # to learn.
    assert (await api.get(f"/api/v1/me/tasks/{task_id}", headers=theirs)).status_code == 404
    assert (
        await api.post(f"/api/v1/me/tasks/{task_id}/cancel", headers=theirs)
    ).status_code == 404

    # And it is still queued: the refusal did not cancel it.
    mine = await api.get(f"/api/v1/me/tasks/{task_id}", headers=headers)
    assert mine.json()["status"] == "queued"
    assert (await api.get("/api/v1/me/tasks", headers=theirs)).json() == []
