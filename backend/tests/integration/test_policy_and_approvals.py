"""Permission policy and the approval pause/resume cycle."""

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
    ToolCall,
    Usage,
)
from tests.integration.conftest import seed_company


class SendsThenAnswers(LLMProvider):
    """Asks to send an email, then (after approval) reports done."""

    provider_key = "gemini"

    def __init__(self, api_key: str) -> None:
        super().__init__(api_key)
        self.calls = 0

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        self.calls += 1
        messages = kwargs.get("messages", [])
        # After a resume the conversation already contains the tool
        # call, so answer instead of asking again.
        already_asked = any(m.tool_calls for m in messages if m.role is Role.ASSISTANT)

        if already_asked:
            return LLMReply(
                message=Message(role=Role.ASSISTANT, content="Email handled."),
                stop_reason=StopReason.END_TURN,
                usage=Usage(prompt_tokens=50, output_tokens=10),
                model="gemini-2.0-flash",
            )

        return LLMReply(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="send_email",
                        arguments={
                            "to": "customer@example.com",
                            "subject": "Your invoice",
                            "body": "Here is the information you asked for.",
                        },
                    )
                ],
            ),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(prompt_tokens=100, output_tokens=20),
            model="gemini-2.0-flash",
        )

    async def check(self, model: str) -> None:
        return None


@pytest.fixture
def stub_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.workers.jobs.agent_run as job

    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: SendsThenAnswers(api_key))


async def _setup(api: AsyncClient, session: AsyncSession) -> dict[str, str]:
    """A person with a connected AI, ready to chat."""
    person = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {person.admin_token}"}

    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "gemini", "api_key": "test-key-abcd1234"},
        headers=headers,
    )
    return headers


async def _say(api: AsyncClient, headers: dict[str, str], text: str) -> str:
    """Start a conversation, say something, and return the turn's task id."""
    created = await api.post("/api/v1/me/conversations", json={"mode": "work"}, headers=headers)
    cid = created.json()["id"]
    sent = await api.post(
        f"/api/v1/me/conversations/{cid}/messages", json={"content": text}, headers=headers
    )
    assert sent.status_code == 202, sent.text
    return str(sent.json()["task_id"])


async def _run(task_id: str) -> dict[str, Any]:
    from app.db.session import get_sessionmaker
    from app.workers.jobs.agent_run import _execute

    return await _execute(get_sessionmaker(), uuid.UUID(task_id))


# ----------------------------------------------------------------- policy


async def test_the_default_policy_is_seeded(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    response = await api.get("/api/v1/me/policies", headers=headers)
    assert response.status_code == 200

    by_key = {(r["scope_value"], r["side_effect"]): r for r in response.json()}
    assert by_key[("email", "destructive")]["setting"] == "ask"
    assert by_key[("email", "write")]["setting"] == "auto"
    assert all(r["is_default"] for r in response.json())


async def test_a_company_can_set_a_rule_looser_than_the_default(
    api: AsyncClient, session: AsyncSession
) -> None:
    """It is their email account. A company that understands its own
    risk may say "we trust this, stop asking"."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    response = await api.put(
        "/api/v1/me/policies",
        json={
            "scope": "pack",
            "scope_value": "email",
            "side_effect": "destructive",
            "setting": "auto",
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["setting"] == "auto"
    assert response.json()["is_default"] is False


async def test_a_company_can_set_a_rule_stricter_than_the_default(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    response = await api.put(
        "/api/v1/me/policies",
        json={"scope": "pack", "scope_value": "web", "side_effect": "read", "setting": "blocked"},
        headers=headers,
    )
    assert response.json()["setting"] == "blocked"


async def test_a_catastrophic_action_cannot_be_enabled(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Refused by the backend, not merely greyed out on the screen: a
    screen-only check is bypassed by calling the API directly."""
    acme = await seed_company(session, api, name="Acme", slug="acme")

    response = await api.put(
        "/api/v1/me/policies",
        json={"scope": "tool", "scope_value": "delete_repository", "setting": "auto"},
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )
    assert response.status_code == 422
    assert "blocked platform-wide" in response.json()["detail"]


async def test_reset_returns_to_the_defaults(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    await api.put(
        "/api/v1/me/policies",
        json={"scope": "pack", "scope_value": "web", "side_effect": "read", "setting": "blocked"},
        headers=headers,
    )
    await api.post("/api/v1/me/policies/reset", headers=headers)

    rows = (await api.get("/api/v1/me/policies", headers=headers)).json()
    assert all(r["is_default"] for r in rows)


async def test_the_tool_catalogue_shows_the_effective_setting(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")

    response = await api.get(
        "/api/v1/me/tools",
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )
    by_name = {t["name"]: t for t in response.json()}

    assert by_name["get_webpage"]["effective_setting"] == "auto"
    assert by_name["save_draft"]["effective_setting"] == "auto"
    assert by_name["send_email"]["effective_setting"] == "ask"


# ----------------------------------------------------------------- approvals


async def test_a_destructive_action_pauses_the_run_for_approval(
    api: AsyncClient, session: AsyncSession, stub_sender: None
) -> None:
    headers = await _setup(api, session)

    task_id = await _say(api, headers, "Reply to the invoice question")
    result = await _run(task_id)
    assert result["status"] == "awaiting_approval"

    pending = await api.get("/api/v1/me/approvals", headers=headers)
    assert len(pending.json()) == 1

    approval = pending.json()[0]
    assert approval["tool_name"] == "send_email"
    # The reviewer sees the real content, not a summary.
    assert approval["proposed"]["to"] == "customer@example.com"
    assert approval["proposed"]["body"] == "Here is the information you asked for."


async def test_approving_resumes_the_run(
    api: AsyncClient, session: AsyncSession, stub_sender: None
) -> None:
    headers = await _setup(api, session)

    task_id = await _say(api, headers, "Reply to the customer")
    await _run(task_id)

    approval_id = (await api.get("/api/v1/me/approvals", headers=headers)).json()[0]["id"]

    decided = await api.post(f"/api/v1/me/approvals/{approval_id}/approve", headers=headers)
    assert decided.json()["status"] == "approved"

    # A worker picks the run back up and continues from the saved
    # conversation, which is why this survives a worker restart.
    await _run(task_id)

    finished = await api.get(f"/api/v1/me/tasks/{task_id}", headers=headers)
    assert finished.json()["status"] == "completed"
    assert finished.json()["run"]["output"] == "Email handled."


async def test_rejecting_ends_the_run_cleanly(
    api: AsyncClient, session: AsyncSession, stub_sender: None
) -> None:
    headers = await _setup(api, session)

    task_id = await _say(api, headers, "Reply to the customer")
    await _run(task_id)

    approval_id = (await api.get("/api/v1/me/approvals", headers=headers)).json()[0]["id"]

    await api.post(f"/api/v1/me/approvals/{approval_id}/reject", headers=headers)

    finished = await api.get(f"/api/v1/me/tasks/{task_id}", headers=headers)
    assert finished.json()["status"] == "failed"
    assert "rejected" in finished.json()["run"]["error_message"].lower()


async def test_setting_the_policy_to_auto_skips_the_approval(
    api: AsyncClient, session: AsyncSession, stub_sender: None
) -> None:
    """With sending set to automatic the run does not pause. It then
    fails on the missing email connection, which is the correct next
    obstacle - the point is that no approval was requested."""
    headers = await _setup(api, session)

    await api.put(
        "/api/v1/me/policies",
        json={
            "scope": "pack",
            "scope_value": "email",
            "side_effect": "destructive",
            "setting": "auto",
        },
        headers=headers,
    )

    result = await _run(await _say(api, headers, "Send it"))

    assert result["status"] != "awaiting_approval"
    assert (await api.get("/api/v1/me/approvals", headers=headers)).json() == []


async def test_always_allow_on_one_tool_needs_no_approval(
    api: AsyncClient, session: AsyncSession, stub_sender: None
) -> None:
    """The switch on Connections and in the tool picker sets a rule for
    one tool. "Always allow" on a send means no approval is requested,
    and setting it back to "Ask me first" brings the approval back."""
    headers = await _setup(api, session)
    rule = {"scope": "tool", "scope_value": "send_email", "side_effect": None}

    saved = await api.put("/api/v1/me/policies", json={**rule, "setting": "auto"}, headers=headers)
    assert saved.status_code == 200, saved.text
    tools = await api.get("/api/v1/me/tools", headers=headers)
    assert {t["name"]: t for t in tools.json()}["send_email"]["effective_setting"] == "auto"

    assert (await _run(await _say(api, headers, "Send it")))["status"] != "awaiting_approval"
    assert (await api.get("/api/v1/me/approvals", headers=headers)).json() == []

    await api.put("/api/v1/me/policies", json={**rule, "setting": "ask"}, headers=headers)
    second = await _run(await _say(api, headers, "Send it again"))
    assert second["status"] == "awaiting_approval"


async def test_blocking_a_tool_stops_it_being_used(
    api: AsyncClient, session: AsyncSession, stub_sender: None
) -> None:
    headers = await _setup(api, session)

    await api.put(
        "/api/v1/me/policies",
        json={"scope": "tool", "scope_value": "send_email", "setting": "blocked"},
        headers=headers,
    )

    task_id = await _say(api, headers, "Send it")
    await _run(task_id)

    task = await api.get(f"/api/v1/me/tasks/{task_id}", headers=headers)
    run_id = task.json()["run"]["id"]
    trace = await api.get(f"/api/v1/me/runs/{run_id}/trace", headers=headers)

    assert any(e["type"] == "tool_blocked" for e in trace.json()["events"])
    assert (await api.get("/api/v1/me/approvals", headers=headers)).json() == []
