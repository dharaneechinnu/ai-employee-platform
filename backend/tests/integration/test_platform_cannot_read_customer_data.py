"""The confidentiality boundary, tested rather than asserted in a document.

The rule is one line: a Platform Admin sees **how much** and
**how healthy**, never **what**.

This matters more than a normal access check. A Platform Admin account
is a master key to every person at once. If it could read customer
content, one stolen password would leak every customer's code, email
and client list simultaneously — the kind of event a person does not
recover from.

So the control is not an access rule that could be misconfigured. It
is the absence of any endpoint that returns the data. These tests
assert that absence, by sweeping the whole platform surface and
looking for customer content in what comes back.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_person

# Strings planted in customer data. None may appear in any
# platform-admin response.
SECRET_TASK_TEXT = "ACME-CONFIDENTIAL-TASK-PAYLOAD"
SECRET_MEMORY_TEXT = "ACME-CONFIDENTIAL-MEMORY-NOTE"
SECRET_API_KEY = "AIza-ACME-CONFIDENTIAL-APIKEY-9876"


async def _platform_token(api: AsyncClient, session: AsyncSession) -> str:
    from app.services.platform_service import PlatformService

    email, password = "staff@platformco.com", "platform-admin-password"
    await PlatformService(session).create_admin(email=email, password=password)
    await session.commit()

    response = await api.post(
        "/api/v1/platform/auth/login",
        json={"email": email, "password": password},
    )
    return str(response.json()["access_token"])


@pytest.fixture
async def seeded(api: AsyncClient, session: AsyncSession) -> dict[str, str]:
    """A person holding content that must never be readable from /platform."""
    acme = await seed_person(session, api, name="Acme")
    headers = {"Authorization": f"Bearer {acme.token}"}

    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "gemini", "api_key": SECRET_API_KEY},
        headers=headers,
    )
    await api.post(
        "/api/v1/me/memory",
        json={"content": SECRET_MEMORY_TEXT},
        headers=headers,
    )
    # Said to the assistant, because a conversation is where a person's
    # content lives now. It becomes both a message and a task.
    conversation = await api.post(
        "/api/v1/me/conversations", json={"mode": "work"}, headers=headers
    )
    await api.post(
        f"/api/v1/me/conversations/{conversation.json()['id']}/messages",
        json={"content": SECRET_TASK_TEXT},
        headers=headers,
    )

    return {"owner_id": str(acme.owner_id), "token": await _platform_token(api, session)}


async def test_no_platform_endpoint_leaks_customer_content(
    api: AsyncClient, seeded: dict[str, str]
) -> None:
    """Sweep every GET under /platform and search the responses.

    Written as a sweep rather than a list of specific checks so that a
    future endpoint is covered the day it is added, not the day
    someone remembers to extend this test.
    """
    headers = {"Authorization": f"Bearer {seeded['token']}"}
    owner_id = seeded["owner_id"]

    spec = (await api.get("/openapi.json")).json()
    platform_gets = [
        path
        for path, operations in spec["paths"].items()
        if "/platform" in path and "get" in operations
    ]
    assert platform_gets, "no platform GET endpoints found; the sweep would pass vacuously"

    checked = 0
    for path in platform_gets:
        response = await api.get(path.replace("{owner_id}", owner_id), headers=headers)
        if response.status_code != 200:
            continue

        body = json.dumps(response.json())
        checked += 1

        for secret, label in (
            (SECRET_TASK_TEXT, "task text"),
            (SECRET_MEMORY_TEXT, "memory content"),
            (SECRET_API_KEY, "an API key"),
        ):
            assert secret not in body, f"{path} leaked {label}"

    assert checked, "no platform endpoint returned 200; the sweep proved nothing"


async def test_the_customer_routes_are_closed_to_platform_staff(
    api: AsyncClient, seeded: dict[str, str]
) -> None:
    """A platform token must not work on the person API either.

    Otherwise the missing /platform endpoint would be no protection at
    all: staff would simply call the customer route instead.
    """
    headers = {"Authorization": f"Bearer {seeded['token']}"}

    for path in (
        "/api/v1/me/tasks",
        "/api/v1/me/memory",
        "/api/v1/me/providers",
        "/api/v1/me/conversations",
    ):
        response = await api.get(path, headers=headers)
        assert response.status_code in (401, 403, 404), f"{path} accepted a platform token"


async def test_a_persons_detail_shows_counts_but_no_content(
    api: AsyncClient, seeded: dict[str, str]
) -> None:
    """The supported shape: how many and how healthy."""
    response = await api.get(
        f"/api/v1/platform/people/{seeded['owner_id']}",
        headers={"Authorization": f"Bearer {seeded['token']}"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["task_count"] == 1
    assert body["active"] is True
    # Whether a provider is connected, never which key.
    assert body["providers"][0]["provider_key"] == "gemini"
    assert body["providers"][0]["connected"] is True
    assert "api_key" not in json.dumps(body)


async def test_the_audit_log_records_platform_actions(
    api: AsyncClient, seeded: dict[str, str]
) -> None:
    headers = {"Authorization": f"Bearer {seeded['token']}"}

    created = await api.post(
        "/api/v1/platform/people",
        json={
            "name": "Globex",
            "slug": "globex",
            "email": "owner@globex.com",
        },
        headers=headers,
    )
    assert created.status_code == 201

    entries = await api.get("/api/v1/platform/audit", headers=headers)
    actions = [e["action"] for e in entries.json()]

    assert "account_created" in actions
    assert "platform_login" in actions
    assert entries.json()[0]["admin_email"] == "staff@platformco.com"
