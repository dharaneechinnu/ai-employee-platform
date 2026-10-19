"""Any AI provider (Claude, your own server, a chosen model) and MCP tool servers."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.agent.mcp.client as mcp_client
from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from tests.fake_mcp import FakeMcpServer
from tests.integration.conftest import seed_company

MCP_URL = "https://crm.acme-tools.com/mcp"
GUIDED = {"what_it_does": "Look after customers.", "what_it_must_never_do": "Never delete data."}


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test hostnames do not resolve here; pretend they are public."""
    import app.core.urls as urls

    monkeypatch.setattr(urls, "is_private_address", lambda host: False)


@pytest.fixture
def fake_server(monkeypatch: pytest.MonkeyPatch) -> FakeMcpServer:
    fake = FakeMcpServer(token="crm-secret-9876")
    monkeypatch.setattr(mcp_client, "transport", fake.transport)
    return fake


async def _company(api: AsyncClient, session: AsyncSession) -> tuple[Any, dict[str, str]]:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    return acme, {"Authorization": f"Bearer {acme.admin_token}"}


# ------------------------------------------------------------ providers


async def test_claude_and_your_own_server_are_on_the_menu(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme, headers = await _company(api, session)
    menu = (
        await api.get(f"/api/v1/orgs/{acme.org_id}/providers/available", headers=headers)
    ).json()
    keys = {p["key"]: p for p in menu}
    assert keys["anthropic"]["default_model"] == "claude-opus-5-5"
    assert "custom" in keys and "mistral" in keys


async def test_your_own_server_needs_an_address_and_a_model(
    api: AsyncClient, session: AsyncSession, public_dns: None
) -> None:
    acme, headers = await _company(api, session)
    url = f"/api/v1/orgs/{acme.org_id}/providers"

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
    acme, headers = await _company(api, session)
    for address in ("https://169.254.169.254/v1", "https://localhost:8000/v1"):
        response = await api.post(
            f"/api/v1/orgs/{acme.org_id}/providers",
            json={"provider_key": "custom", "base_url": address, "model": "x"},
            headers=headers,
        )
        assert response.status_code == 422
        assert "private" in response.json()["detail"]


async def test_a_company_picks_its_model_and_runs_use_it(
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
    acme, headers = await _company(api, session)
    await api.post(
        f"/api/v1/orgs/{acme.org_id}/providers",
        json={"provider_key": "anthropic", "api_key": "sk-ant-test-1234"},
        headers=headers,
    )
    picked = await api.put(
        f"/api/v1/orgs/{acme.org_id}/providers/anthropic/model",
        json={"model": "claude-haiku-5-5"},
        headers=headers,
    )
    assert picked.json()["default_model"] == "claude-haiku-5-5"
    assert picked.json()["model_chosen"] is True

    employee = await _employee(api, acme.org_id, headers, [])
    task = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee, "input": "Hi"},
        headers=headers,
    )
    await _run(task.json()["id"])
    assert used == [("anthropic", "claude-haiku-5-5")]

    back = await api.put(
        f"/api/v1/orgs/{acme.org_id}/providers/anthropic/model",
        json={"model": None},
        headers=headers,
    )
    assert back.json()["default_model"] == "claude-opus-5-5"


# ------------------------------------------------------------ MCP


async def test_connecting_a_server_lists_its_tools_with_safe_permissions(
    api: AsyncClient, session: AsyncSession, public_dns: None, fake_server: FakeMcpServer
) -> None:
    acme, headers = await _company(api, session)

    added = await api.post(
        f"/api/v1/orgs/{acme.org_id}/mcp-servers",
        json={"name": "CRM", "url": MCP_URL, "token": "crm-secret-9876"},
        headers=headers,
    )
    assert added.status_code == 201, added.text
    server = added.json()
    assert server["token_last4"] == "9876"
    assert "crm-secret" not in added.text  # write-only, like every secret
    assert [t["name"] for t in server["tools"]] == [
        "mcp__crm__find_customer",
        "mcp__crm__update_deal_stage",
        "mcp__crm__delete_contact",
    ]

    catalogue = (await api.get(f"/api/v1/orgs/{acme.org_id}/tools", headers=headers)).json()
    mcp = {t["name"]: t for t in catalogue if t["name"].startswith("mcp__")}
    assert mcp["mcp__crm__find_customer"]["effective_setting"] == "auto"
    assert mcp["mcp__crm__find_customer"]["label"] == "Find a customer"
    assert mcp["mcp__crm__find_customer"]["pack_label"] == "CRM"
    assert mcp["mcp__crm__update_deal_stage"]["effective_setting"] == "ask"
    assert mcp["mcp__crm__delete_contact"]["effective_setting"] == "blocked"


async def test_a_server_that_does_not_answer_is_not_saved(
    api: AsyncClient, session: AsyncSession, public_dns: None, fake_server: FakeMcpServer
) -> None:
    acme, headers = await _company(api, session)
    wrong_token = await api.post(
        f"/api/v1/orgs/{acme.org_id}/mcp-servers",
        json={"name": "CRM", "url": MCP_URL, "token": "wrong-token"},
        headers=headers,
    )
    assert wrong_token.status_code == 422
    assert "refused the access token" in wrong_token.json()["detail"]
    assert (await api.get(f"/api/v1/orgs/{acme.org_id}/mcp-servers", headers=headers)).json() == []


async def test_another_company_never_sees_the_tools(
    api: AsyncClient, session: AsyncSession, public_dns: None, fake_server: FakeMcpServer
) -> None:
    acme, headers = await _company(api, session)
    await api.post(
        f"/api/v1/orgs/{acme.org_id}/mcp-servers",
        json={"name": "CRM", "url": MCP_URL, "token": "crm-secret-9876"},
        headers=headers,
    )
    other = await seed_company(session, api, name="Globex", slug="globex")
    other_headers = {"Authorization": f"Bearer {other.admin_token}"}
    catalogue = (await api.get(f"/api/v1/orgs/{other.org_id}/tools", headers=other_headers)).json()
    assert not any(t["name"].startswith("mcp__") for t in catalogue)


async def test_an_employee_uses_an_mcp_tool_in_a_real_run(
    api: AsyncClient,
    session: AsyncSession,
    public_dns: None,
    fake_server: FakeMcpServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.workers.jobs.agent_run as job

    class LooksUpThenAnswers(LLMProvider):
        provider_key = "gemini"

        async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
            messages: list[Message] = kwargs["messages"]
            tool_names = {t.name for t in kwargs.get("tools") or []}
            assert "mcp__crm__find_customer" in tool_names
            result = next((m for m in messages if m.role is Role.TOOL), None)
            if result is None:
                return LLMReply(
                    message=Message(
                        role=Role.ASSISTANT,
                        tool_calls=[ToolCall("c1", "mcp__crm__find_customer", {"query": "Asha"})],
                    ),
                    stop_reason=StopReason.TOOL_USE,
                    usage=Usage(50, 10),
                    model="gemini-2.0-flash",
                )
            return LLMReply(
                message=Message(role=Role.ASSISTANT, content=f"Found: {result.content}"),
                stop_reason=StopReason.END_TURN,
                usage=Usage(80, 20),
                model="gemini-2.0-flash",
            )

        async def check(self, model: str) -> None:
            return None

    monkeypatch.setattr(
        job, "build_provider", lambda key, api_key, **_: LooksUpThenAnswers(api_key)
    )
    acme, headers = await _company(api, session)
    await api.post(
        f"/api/v1/orgs/{acme.org_id}/providers",
        json={"provider_key": "gemini", "api_key": "test-key-abcd1234"},
        headers=headers,
    )
    await api.post(
        f"/api/v1/orgs/{acme.org_id}/mcp-servers",
        json={"name": "CRM", "url": MCP_URL, "token": "crm-secret-9876"},
        headers=headers,
    )
    employee = await _employee(api, acme.org_id, headers, ["mcp__crm__find_customer"])

    task = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee, "input": "Who is Asha?"},
        headers=headers,
    )
    outcome = await _run(task.json()["id"])

    assert outcome["status"] == "completed"
    # The token reached the server; it never reached the model.
    assert fake_server.calls == [("find_customer", {"query": "Asha"})]
    detail = (
        await api.get(f"/api/v1/orgs/{acme.org_id}/tasks/{task.json()['id']}", headers=headers)
    ).json()
    assert "Asha Rao" in (detail["run"]["output"] or "")


async def test_a_write_tool_from_a_server_waits_for_approval(
    api: AsyncClient,
    session: AsyncSession,
    public_dns: None,
    fake_server: FakeMcpServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.workers.jobs.agent_run as job

    class MovesADeal(LLMProvider):
        provider_key = "gemini"

        async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
            return LLMReply(
                message=Message(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            "c1", "mcp__crm__update_deal_stage", {"deal_id": "D-9", "stage": "won"}
                        )
                    ],
                ),
                stop_reason=StopReason.TOOL_USE,
                usage=Usage(50, 10),
                model="gemini-2.0-flash",
            )

        async def check(self, model: str) -> None:
            return None

    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: MovesADeal(api_key))
    acme, headers = await _company(api, session)
    await api.post(
        f"/api/v1/orgs/{acme.org_id}/providers",
        json={"provider_key": "gemini", "api_key": "test-key-abcd1234"},
        headers=headers,
    )
    await api.post(
        f"/api/v1/orgs/{acme.org_id}/mcp-servers",
        json={"name": "CRM", "url": MCP_URL, "token": "crm-secret-9876"},
        headers=headers,
    )
    employee = await _employee(api, acme.org_id, headers, ["mcp__crm__update_deal_stage"])
    task = await api.post(
        f"/api/v1/orgs/{acme.org_id}/tasks",
        json={"employee_id": employee, "input": "Mark D-9 as won"},
        headers=headers,
    )
    outcome = await _run(task.json()["id"])

    assert outcome["status"] == "awaiting_approval"
    assert fake_server.calls == []  # nothing happened before a person said yes
    approvals = (await api.get(f"/api/v1/orgs/{acme.org_id}/approvals", headers=headers)).json()
    assert approvals[0]["tool_name"] == "mcp__crm__update_deal_stage"
    assert approvals[0]["side_effect"] == "write"
    assert approvals[0]["proposed"] == {"deal_id": "D-9", "stage": "won"}


# ------------------------------------------------------------ helpers


async def _employee(
    api: AsyncClient, org_id: uuid.UUID, headers: dict[str, str], tools: list[str]
) -> str:
    created = await api.post(
        f"/api/v1/orgs/{org_id}/ai-employees",
        json={
            "name": "Ravi",
            "config": {"guided": GUIDED, "model": "auto", "enabled_tools": tools},
        },
        headers=headers,
    )
    employee_id = created.json()["id"]
    await api.post(f"/api/v1/orgs/{org_id}/ai-employees/{employee_id}/activate", headers=headers)
    return employee_id


async def _run(task_id: str) -> dict[str, Any]:
    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    return await _execute(get_sessionmaker(), uuid.UUID(task_id))
