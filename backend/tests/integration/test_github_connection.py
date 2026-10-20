"""Connecting GitHub by token, and its tools reaching the assistant."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.providers.base import LLMProvider, LLMReply, Message, Role, StopReason, Usage
from tests.integration.conftest import seed_person

TOKEN = "github_pat_test_ABCD1234"


@pytest.fixture
def github_api(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import app.services.connection_service as service

    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"message": "Bad credentials"})
        return httpx.Response(200, json={"login": "asha-dev"})

    monkeypatch.setattr(
        service, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    return seen


async def test_github_connects_with_a_token_and_names_the_account(
    api: AsyncClient, session: AsyncSession, github_api: list[str]
) -> None:
    person = await seed_person(session, api)
    headers = {"Authorization": f"Bearer {person.token}"}

    menu = (await api.get("/api/v1/me/connections/available", headers=headers)).json()
    github = next(c for c in menu if c["kind"] == "github")
    assert github["secret_label"] == "Personal access token"
    assert "github_propose_change" in github["tools"]

    saved = await api.post(
        "/api/v1/me/connections",
        json={"kind": "github", "label": "GitHub", "secret": TOKEN, "config": {}},
        headers=headers,
    )
    assert saved.status_code in (200, 201), saved.text
    conn_id = saved.json()["id"]
    tested = await api.post(f"/api/v1/me/connections/{conn_id}/test", headers=headers)
    assert tested.json()["status"] == "connected", tested.text

    listed = (await api.get("/api/v1/me/connections", headers=headers)).text
    assert "asha-dev" in listed
    assert TOKEN not in listed  # write-only, like every secret


async def test_a_refused_token_is_said_plainly(
    api: AsyncClient, session: AsyncSession, github_api: list[str]
) -> None:
    person = await seed_person(session, api)
    headers = {"Authorization": f"Bearer {person.token}"}
    saved = await api.post(
        "/api/v1/me/connections",
        json={"kind": "github", "label": "GitHub", "secret": "wrong-token-0000", "config": {}},
        headers=headers,
    )
    tested = await api.post(f"/api/v1/me/connections/{saved.json()['id']}/test", headers=headers)
    assert tested.json()["status"] == "failed"
    assert "refused the token" in tested.json()["last_error"]


async def test_once_connected_the_code_assistant_has_the_github_tools(
    api: AsyncClient,
    session: AsyncSession,
    github_api: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.workers.jobs.agent_run as job

    offered: list[set[str]] = []
    prompts: list[str] = []

    class Looks(LLMProvider):
        provider_key = "gemini"

        async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
            offered.append({t.name for t in kwargs.get("tools") or []})
            prompts.append(kwargs["messages"][0].content or "")
            return LLMReply(
                message=Message(role=Role.ASSISTANT, content="ok"),
                stop_reason=StopReason.END_TURN,
                usage=Usage(1, 1),
                model=kwargs["model"],
            )

        async def check(self, model: str) -> None:
            return None

    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: Looks(api_key))
    person = await seed_person(session, api)
    headers = {"Authorization": f"Bearer {person.token}"}
    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "gemini", "api_key": "gemini-test-key-1234"},
        headers=headers,
    )

    async def ask() -> None:
        from app.db.session import get_sessionmaker
        from app.workers.jobs.agent_run import _execute

        cid = (
            await api.post("/api/v1/me/conversations", json={"mode": "code"}, headers=headers)
        ).json()["id"]
        sent = await api.post(
            f"/api/v1/me/conversations/{cid}/messages",
            json={"content": "Why is CI red on acme/api?"},
            headers=headers,
        )
        await _execute(get_sessionmaker(), uuid.UUID(sent.json()["task_id"]))

    await ask()
    assert "github_ci_status" not in offered[-1]  # not connected yet
    assert "senior software engineer" in prompts[-1]

    saved = await api.post(
        "/api/v1/me/connections",
        json={"kind": "github", "label": "GitHub", "secret": TOKEN, "config": {}},
        headers=headers,
    )
    await api.post(f"/api/v1/me/connections/{saved.json()['id']}/test", headers=headers)
    await ask()
    assert {"github_ci_status", "github_pr_diff", "github_propose_change"} <= offered[-1]
