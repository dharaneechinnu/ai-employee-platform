"""One-click connections, notifications, and approving from a link.

No real Google, Microsoft, SMTP server or Slack is contacted: the HTTP
clients and the two transports are replaced with fakes, so these tests
check our side of each conversation.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from tests.integration.conftest import seed_person
from tests.integration.test_policy_and_approvals import SendsThenAnswers, _run, _say, _setup

ACCESS = "ya29.fake-access-token-0001"
REFRESH = "1//fake-refresh-token-zz99"


@pytest.fixture
def stub_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model that asks to send an email, then finishes once allowed."""
    import app.workers.jobs.agent_run as job

    monkeypatch.setattr(job, "build_provider", lambda key, api_key, **_: SendsThenAnswers(api_key))


@pytest.fixture
def oauth_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-456")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_google(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Answers the token and userinfo endpoints like Google would."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode()) if request.content else {}
        seen.append({"url": str(request.url), "body": body})
        if request.url.path == "/token":
            grant = body.get("grant_type", [""])[0]
            if grant == "authorization_code":
                return httpx.Response(
                    200,
                    json={
                        "access_token": ACCESS,
                        "refresh_token": REFRESH,
                        "expires_in": 3600,
                        "scope": "openid email",
                    },
                )
            return httpx.Response(200, json={"access_token": "ya29.refreshed", "expires_in": 3600})
        if "userinfo" in request.url.path:
            return httpx.Response(200, json={"email": "ops@acme.com", "name": "Acme Ops"})
        return httpx.Response(404)

    import app.services.connection_service as svc

    monkeypatch.setattr(
        svc, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return seen


async def _connect_google(api: AsyncClient, owner_id: uuid.UUID, token: str) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"}
    start = await api.post("/api/v1/me/connections/oauth/google/start", headers=headers)
    assert start.status_code == 200, start.text
    query = parse_qs(urlparse(start.json()["authorize_url"]).query)
    return await api.get(
        "/api/v1/oauth/google/callback",
        params={"code": "auth-code", "state": query["state"][0]},
    )


# ----------------------------------------------------------------- connections


async def test_the_catalogue_lists_one_click_apps_and_their_tools(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_person(session, api, name="Acme")
    response = await api.get(
        "/api/v1/me/connections/available",
        headers={"Authorization": f"Bearer {acme.token}"},
    )
    assert response.status_code == 200
    by_kind = {c["kind"]: c for c in response.json()}
    assert by_kind["google"]["auth"] == "oauth"
    assert "gmail_send" in by_kind["google"]["tools"]
    assert "onedrive_read" in by_kind["microsoft"]["tools"]
    # No OAuth app registered in tests, so the UI can grey it out.
    assert by_kind["google"]["configured"] is False


async def test_starting_a_connection_without_an_oauth_app_says_why(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_person(session, api, name="Acme")
    response = await api.post(
        "/api/v1/me/connections/oauth/google/start",
        headers={"Authorization": f"Bearer {acme.token}"},
    )
    assert response.status_code == 422
    assert "not set up" in response.json()["detail"]


async def test_one_click_google_connection_end_to_end(
    api: AsyncClient,
    session: AsyncSession,
    oauth_configured: None,
    fake_google: list[dict[str, Any]],
) -> None:
    acme = await seed_person(session, api, name="Acme")
    callback = await _connect_google(api, acme.owner_id, acme.token)

    assert callback.status_code == 303
    assert "connected=google" in callback.headers["location"]

    listed = await api.get(
        "/api/v1/me/connections",
        headers={"Authorization": f"Bearer {acme.token}"},
    )
    [conn] = listed.json()
    assert conn["kind"] == "google"
    assert conn["account"] == "ops@acme.com"
    assert conn["status"] == "connected"
    # Write-only: neither token ever comes back out.
    assert ACCESS not in listed.text and REFRESH not in listed.text


async def test_a_tampered_state_is_refused(
    api: AsyncClient, session: AsyncSession, oauth_configured: None
) -> None:
    response = await api.get(
        "/api/v1/oauth/google/callback", params={"code": "x", "state": "not-a-real-state"}
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]


async def test_an_expiring_token_is_refreshed_before_a_run(
    api: AsyncClient,
    session: AsyncSession,
    oauth_configured: None,
    fake_google: list[dict[str, Any]],
) -> None:
    from sqlalchemy import select

    from app.core.crypto import decrypt, encrypt
    from app.db.models.policy import Connection
    from app.services.connection_service import ConnectionService

    acme = await seed_person(session, api, name="Acme")
    await _connect_google(api, acme.owner_id, acme.token)

    conn = await session.scalar(select(Connection).where(Connection.owner_id == acme.owner_id))
    assert conn is not None
    secret = json.loads(decrypt(conn.credential_enc, scope=acme.owner_id))
    secret["expires_at"] = int(time.time()) + 60  # about to expire
    conn.credential_enc = encrypt(json.dumps(secret), scope=acme.owner_id)
    await session.commit()

    grants = await ConnectionService(session, acme.owner_id).resolve_grants()
    assert grants["google"].credential == "ya29.refreshed"
    assert grants["google"].config["account"] == "ops@acme.com"


async def test_a_manual_mailbox_connection_is_stored_write_only(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_person(session, api, name="Acme")
    response = await api.post(
        "/api/v1/me/connections",
        json={
            "kind": "email",
            "label": "Support inbox",
            "secret": "app-password-wxyz",
            "config": {"username": "support@acme.com"},
        },
        headers={"Authorization": f"Bearer {acme.token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account"] == "support@acme.com"
    assert body["credential_last4"] == "wxyz"
    assert "app-password" not in response.text


async def test_one_click_kinds_cannot_be_added_by_hand(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_person(session, api, name="Acme")
    response = await api.post(
        "/api/v1/me/connections",
        json={"kind": "google", "label": "x", "secret": "y", "config": {}},
        headers={"Authorization": f"Bearer {acme.token}"},
    )
    assert response.status_code == 422


# ----------------------------------------------------------------- notifications


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, list[Any]]]:
    """Capture email and Slack instead of sending them."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM", "robot@example.com")
    get_settings.cache_clear()
    box: dict[str, list[Any]] = {"email": [], "slack": []}

    async def fake_email(to: str, subject: str, text: str, html: str) -> None:
        box["email"].append({"to": to, "subject": subject, "text": text})

    async def fake_slack(url: str, payload: dict[str, Any]) -> None:
        box["slack"].append(payload)

    import app.services.notification_service as notify

    monkeypatch.setattr(notify, "send_email", fake_email)
    monkeypatch.setattr(notify, "post_slack", fake_slack)
    yield box
    get_settings.cache_clear()


async def test_notification_settings_default_and_update(
    api: AsyncClient, session: AsyncSession, outbox: dict[str, list[Any]]
) -> None:
    acme = await seed_person(session, api, name="Acme")
    headers = {"Authorization": f"Bearer {acme.token}"}
    url = "/api/v1/me/notifications"

    initial = (await api.get(url, headers=headers)).json()
    assert initial["email_enabled"] is True
    assert initial["email_available"] is True
    assert initial["slack_connected"] is False

    bad = await api.put(
        url,
        json={"slack_enabled": True, "slack_webhook_url": "https://evil.example/x"},
        headers=headers,
    )
    assert bad.status_code == 422

    hook = "https://hooks.slack.com/services/T000/B000/abcd"
    good = await api.put(
        url, json={"slack_enabled": True, "slack_webhook_url": hook}, headers=headers
    )
    assert good.status_code == 200
    assert good.json()["slack_connected"] is True
    assert good.json()["slack_webhook_last4"] == "abcd"
    assert hook not in good.text

    test = await api.post(f"{url}/test", headers=headers)
    assert test.json()["slack"] == "sent"
    assert test.json()["email"].startswith("sent to")
    assert len(outbox["slack"]) == 1


async def test_approve_from_an_email_link_resumes_the_run(
    api: AsyncClient,
    session: AsyncSession,
    stub_sender: None,
    outbox: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole loop: a run pauses, the person is emailed a link, the
    link approves without signing in, and the run resumes and finishes."""
    import app.api.v1.routes.approval_links as links

    queued: list[uuid.UUID] = []

    async def fake_enqueue(task_id: uuid.UUID, **_: object) -> str:
        queued.append(task_id)
        return "job"

    monkeypatch.setattr(links, "enqueue_task", fake_enqueue)

    headers = await _setup(api, session)
    my_email = (await api.get("/api/v1/auth/me", headers=headers)).json()["email"]
    await api.put(
        "/api/v1/me/notifications",
        json={"slack_enabled": True, "slack_webhook_url": "https://hooks.slack.com/services/x"},
        headers=headers,
    )

    task_id = await _say(api, headers, "Send the invoice email.")
    paused = await _run(task_id)
    assert paused["status"] == "awaiting_approval"

    [email] = [e for e in outbox["email"] if e["to"] == my_email]
    assert "Approval needed" in email["subject"]
    assert "customer@example.com" in email["text"]
    assert outbox["slack"], "the Slack channel should hear about it too"

    link = next(line for line in email["text"].splitlines() if line.startswith("Approve: "))
    token = urlparse(link.removeprefix("Approve: ")).path.rsplit("/", 1)[-1]

    # Reading the link is safe: it decides nothing.
    view = await api.get(f"/api/v1/approval-links/{token}")
    assert view.status_code == 200
    assert view.json()["status"] == "pending"
    assert view.json()["acting_as"] == my_email
    assert view.json()["requires_sign_in"] is False

    decided = await api.post(f"/api/v1/approval-links/{token}/decide", json={"approve": True})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"
    assert queued == [uuid.UUID(task_id)]

    # A second click cannot decide it twice.
    again = await api.post(f"/api/v1/approval-links/{token}/decide", json={"approve": False})
    assert again.status_code == 409

    finished = await _run(task_id)
    assert finished["status"] == "completed"
    # No "it finished" email: a chat reply appears in the chat the
    # person is already in, so only things that need them are sent.
    assert not any("finished" in e["subject"] for e in outbox["email"])


async def test_a_forged_approval_link_is_not_found(api: AsyncClient) -> None:
    response = await api.get("/api/v1/approval-links/forged.token.value")
    assert response.status_code == 404


async def test_an_access_token_is_not_an_approval_link(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Purposes are not interchangeable: a session token pasted into a
    link must not be read as one."""
    acme = await seed_person(session, api, name="Acme")
    response = await api.get(f"/api/v1/approval-links/{acme.token}")
    assert response.status_code == 404
