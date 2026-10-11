"""Tasks end to end: create, run, stream, cancel.

The worker job is executed directly rather than through Redis. That
keeps the test fast and deterministic while still exercising the real
code path — the same function arq calls in production.

The provider is stubbed, because a real model gives a different answer
every time and costs money and rate limit on every CI run.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.providers.base import LLMProvider, LLMReply, Message, Role, StopReason, Usage
from tests.integration.conftest import seed_company

GUIDED = {
    "what_it_does": "Answer questions about bugs.",
    "what_it_must_never_do": "Never delete code.",
}


class StubProvider(LLMProvider):
    """Answers immediately, with no tool calls."""

    provider_key = "gemini"

    def __init__(self, api_key: str, answer: str = "The bug is on line 24.") -> None:
        super().__init__(api_key)
        self.answer = answer

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        return LLMReply(
            message=Message(role=Role.ASSISTANT, content=self.answer),
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

    monkeypatch.setattr(job, "build_provider", lambda key, api_key: StubProvider(api_key))


async def _setup(api: AsyncClient, session: AsyncSession) -> tuple[Any, str, str]:
    """A company with a connected provider and one active AI Employee."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    await api.post(
        f"/api/v1/orgs/{acme.org_id}/providers",
        json={"provider_key": "gemini", "api_key": "test-key-abcd1234"},
        headers=headers,
    )

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees",
        json={
            "name": "Bug Fixer Bot",
            "job_title": "GitHub Helper",
            "config": {"guided": GUIDED, "model": "gemini-2.0-flash", "enabled_tools": []},
        },
        headers=headers,
    )
    employee_id = created.json()["id"]
    await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees/{employee_id}/activate", headers=headers
    )
    return acme, employee_id, acme.admin_token


async def test_creating_a_task_returns_immediately(api: AsyncClient, session: AsyncSession) -> None:
    """The API must not wait for the agent: a run takes minutes and a
    browser gives up long before that."""
    acme, employee_id, token = await _setup(api, session)

    response = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee_id, "input": "Look at bug 42"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["run"] is None


async def test_the_worker_runs_the_task_and_records_the_result(
    api: AsyncClient, session: AsyncSession, stub_provider: None
) -> None:
    acme, employee_id, token = await _setup(api, session)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee_id, "input": "Look at bug 42"},
        headers=headers,
    )
    task_id = created.json()["id"]

    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    result = await _execute(get_sessionmaker(), uuid.UUID(task_id))
    assert result["stop_cause"] == "completed"

    finished = await api.get(f"/api/v1/orgs/{acme.org_id}/tasks/{task_id}", headers=headers)
    body = finished.json()
    assert body["status"] == "completed"
    assert body["run"]["output"] == "The bug is on line 24."
    assert body["run"]["prompt_tokens"] == 120
    assert float(body["run"]["estimated_cost_usd"]) > 0


async def test_the_run_trace_records_every_step(
    api: AsyncClient, session: AsyncSession, stub_provider: None
) -> None:
    """The event log is what makes a run debuggable and auditable."""
    acme, employee_id, token = await _setup(api, session)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee_id, "input": "Look at bug 42"},
        headers=headers,
    )
    task_id = created.json()["id"]

    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    await _execute(get_sessionmaker(), uuid.UUID(task_id))

    task = await api.get(f"/api/v1/orgs/{acme.org_id}/tasks/{task_id}", headers=headers)
    run_id = task.json()["run"]["id"]

    trace = await api.get(f"/api/v1/orgs/{acme.org_id}/runs/{run_id}/trace", headers=headers)
    events = trace.json()["events"]

    assert [e["type"] for e in events][:2] == ["run_started", "thinking"]
    # seq is gap-free, which is what lets a reconnecting client resume.
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert trace.json()["llm_calls"][0]["prompt_tokens"] == 120


async def test_a_task_without_a_connected_provider_fails_with_a_clear_message(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/ai-employees",
        json={"name": "Bot", "config": {"guided": GUIDED, "model": "gemini-2.0-flash"}},
        headers=headers,
    )
    employee_id = created.json()["id"]

    task = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee_id, "input": "do something"},
        headers=headers,
    )
    task_id = task.json()["id"]

    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    await _execute(get_sessionmaker(), uuid.UUID(task_id))

    finished = await api.get(f"/api/v1/orgs/{acme.org_id}/tasks/{task_id}", headers=headers)
    body = finished.json()
    assert body["status"] == "failed"
    assert "No API key is connected" in body["run"]["error_message"]


async def test_cancelling_a_queued_task(api: AsyncClient, session: AsyncSession) -> None:
    acme, employee_id, token = await _setup(api, session)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee_id, "input": "Look at bug 42"},
        headers=headers,
    )
    task_id = created.json()["id"]

    cancelled = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks/{task_id}/cancel", headers=headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


async def test_a_cancelled_task_is_not_run_by_the_worker(
    api: AsyncClient, session: AsyncSession, stub_provider: None
) -> None:
    acme, employee_id, token = await _setup(api, session)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee_id, "input": "Look at bug 42"},
        headers=headers,
    )
    task_id = created.json()["id"]
    await api.post(f"/api/v1/orgs/{acme.org_id}/tasks/{task_id}/cancel", headers=headers)

    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    # The worker sees it is no longer queued and does not run it.
    result = await _execute(get_sessionmaker(), uuid.UUID(task_id))
    assert result["status"] == "cancelled"


async def test_tasks_appear_in_the_list(api: AsyncClient, session: AsyncSession) -> None:
    acme, employee_id, token = await _setup(api, session)
    headers = {"Authorization": f"Bearer {token}"}

    await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee_id, "input": "first"},
        headers=headers,
    )

    listed = await api.get(f"/api/v1/orgs/{acme.org_id}/tasks", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_a_member_can_create_a_task(api: AsyncClient, session: AsyncSession) -> None:
    """Member uses the AI Employees an Admin built."""
    acme, employee_id, _ = await _setup(api, session)

    response = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee_id, "input": "please look at this"},
        headers={"Authorization": f"Bearer {acme.member_token}"},
    )
    assert response.status_code == 202


async def test_company_a_cannot_read_company_b_tasks(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme, employee_id, token = await _setup(api, session)
    globex = await seed_company(session, api, name="Globex", slug="globex")

    created = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee_id, "input": "secret work"},
        headers={"Authorization": f"Bearer {token}"},
    )
    task_id = created.json()["id"]

    response = await api.get(
        f"/api/v1/orgs/{globex.org_id}/tasks/{task_id}",
        headers={"Authorization": f"Bearer {globex.admin_token}"},
    )
    assert response.status_code == 404
