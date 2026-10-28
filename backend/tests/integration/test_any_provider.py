"""Any AI provider: Claude, your own server, a chosen model."""

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
    Role,
    StopReason,
    Usage,
)
from tests.integration.conftest import seed_person


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test hostnames do not resolve here; pretend they are public."""
    import app.core.urls as urls

    monkeypatch.setattr(urls, "is_private_address", lambda host: False)


async def _person(api: AsyncClient, session: AsyncSession) -> tuple[Any, dict[str, str]]:
    acme = await seed_person(session, api, name="Acme")
    return acme, {"Authorization": f"Bearer {acme.token}"}


# ------------------------------------------------------------ providers


async def test_claude_and_your_own_server_are_on_the_menu(
    api: AsyncClient, session: AsyncSession
) -> None:
    _acme, headers = await _person(api, session)
    menu = (await api.get("/api/v1/me/providers/available", headers=headers)).json()
    keys = {p["key"]: p for p in menu}
    assert keys["anthropic"]["default_model"] == "claude-opus-5-5"
    assert "custom" in keys and "mistral" in keys


async def test_your_own_server_needs_an_address_and_a_model(
    api: AsyncClient, session: AsyncSession, public_dns: None
) -> None:
    _acme, headers = await _person(api, session)
    url = "/api/v1/me/providers"

    missing = await api.post(
        url, json={"provider_key": "custom", "model": "llama"}, headers=headers
    )
    assert missing.status_code == 422 and "address" in missing.json()["detail"]

    plain_http = await api.post(
        url,
        json={"provider_key": "custom", "base_url": "http://llm.acme.com/v1", "model": "llama"},
        headers=headers,
    )
    assert plain_http.status_code == 422 and "https" in plain_http.json()["detail"]

    # No key: a self-hosted server often has none.
    ok = await api.post(
        url,
        json={
            "provider_key": "custom",
            "base_url": "https://llm.acme.com/v1/",
            "model": "qwen3-32b",
            "label": "Acme Qwen",
        },
        headers=headers,
    )
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["display_name"] == "Acme Qwen"
    assert body["base_url"] == "https://llm.acme.com/v1"
    assert body["default_model"] == "qwen3-32b"
    assert body["key_last4"] == "none"


async def test_a_private_address_is_refused(api: AsyncClient, session: AsyncSession) -> None:
    """Otherwise our servers could be made to call cloud metadata or internal services."""
    _acme, headers = await _person(api, session)
    for address in ("https://169.254.169.254/v1", "https://localhost:8000/v1"):
        response = await api.post(
            "/api/v1/me/providers",
            json={"provider_key": "custom", "base_url": address, "model": "x"},
            headers=headers,
        )
        assert response.status_code == 422
        assert "private" in response.json()["detail"]


async def test_a_person_picks_its_model_and_runs_use_it(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.workers.jobs.agent_run as job

    used: list[tuple[str, str]] = []

    class Answers(LLMProvider):
        provider_key = "anthropic"

        async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
            used.append(("anthropic", kwargs["model"]))
            return LLMReply(
                message=Message(role=Role.ASSISTANT, content="Done."),
                stop_reason=StopReason.END_TURN,
                usage=Usage(10, 5),
                model=kwargs["model"],
            )

        async def check(self, model: str) -> None:
            return None

    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: Answers(api_key))
    _acme, headers = await _person(api, session)
    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "anthropic", "api_key": "sk-ant-test-1234"},
        headers=headers,
    )
    picked = await api.put(
        "/api/v1/me/providers/anthropic/model",
        json={"model": "claude-haiku-5-5"},
        headers=headers,
    )
    assert picked.json()["default_model"] == "claude-haiku-5-5"
    assert picked.json()["model_chosen"] is True

    await _run(await _say(api, headers, "Hi"))
    assert used == [("anthropic", "claude-haiku-5-5")]

    back = await api.put(
        "/api/v1/me/providers/anthropic/model",
        json={"model": None},
        headers=headers,
    )
    assert back.json()["default_model"] == "claude-opus-5-5"


# ------------------------------------------------------------ helpers


async def _say(api: AsyncClient, headers: dict[str, str], text: str) -> str:
    """Start a conversation, say something, and return the turn's task id."""
    created = await api.post("/api/v1/me/conversations", json={"mode": "work"}, headers=headers)
    sent = await api.post(
        f"/api/v1/me/conversations/{created.json()['id']}/messages",
        json={"content": text},
        headers=headers,
    )
    assert sent.status_code == 202, sent.text
    return str(sent.json()["task_id"])


async def _run(task_id: str) -> dict[str, Any]:
    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    return await _execute(get_sessionmaker(), uuid.UUID(task_id))
