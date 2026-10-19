"""The one-click sign-in apps, and who may touch them.

A company's Connections page shows "Connect Google Workspace" greyed
out until the platform registers an OAuth app. Google and Microsoft
issue one app per *application*, not per customer, so that setting is
platform-wide — and it used to arrive only as an environment variable,
which meant no Platform Admin could switch it on at all.

These tests cover the two halves: that registering it from the
platform screen actually unlocks the button for every company, and
that a company admin cannot reach the setting themselves.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_company

CLIENT_ID = "1234567890-example.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-example-secret-value-4421"


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
async def staff(api: AsyncClient, session: AsyncSession) -> dict[str, str]:
    return {"Authorization": f"Bearer {await _platform_token(api, session)}"}


async def test_unregistered_providers_are_still_listed(
    api: AsyncClient, staff: dict[str, str]
) -> None:
    """A provider that vanished when unset could never be switched on."""
    response = await api.get("/api/v1/platform/oauth-apps", headers=staff)
    assert response.status_code == 200

    apps = {a["provider"]: a for a in response.json()}
    assert {"google", "microsoft"} <= set(apps)
    assert apps["google"]["configured"] is False
    assert apps["google"]["client_id"] is None
    # The redirect address is the usual reason a sign-in fails, so it
    # is shown before anything is registered, not after.
    assert apps["google"]["redirect_uri"].endswith("/oauth/google/callback")


async def test_registering_an_app_unlocks_the_button_for_a_company(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    """The whole point: a platform setting that reaches every tenant."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    company = {"Authorization": f"Bearer {acme.admin_token}"}

    async def google_configured() -> bool:
        listing = await api.get(
            f"/api/v1/me/connections/available", headers=company
        )
        return next(a for a in listing.json() if a["kind"] == "google")["configured"]

    assert await google_configured() is False

    saved = await api.put(
        "/api/v1/platform/oauth-apps/google",
        json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        headers=staff,
    )
    assert saved.status_code == 200
    assert saved.json()["configured"] is True

    assert await google_configured() is True

    # And the button now leads somewhere real.
    start = await api.post(
        f"/api/v1/me/connections/oauth/google/start", headers=company
    )
    assert start.status_code == 200
    assert CLIENT_ID in start.json()["authorize_url"]


async def test_pausing_an_app_closes_the_button_again(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    company = {"Authorization": f"Bearer {acme.admin_token}"}

    await api.put(
        "/api/v1/platform/oauth-apps/google",
        json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        headers=staff,
    )
    paused = await api.patch(
        "/api/v1/platform/oauth-apps/google", json={"enabled": False}, headers=staff
    )
    assert paused.status_code == 200
    assert paused.json()["configured"] is False

    listing = await api.get(f"/api/v1/me/connections/available", headers=company)
    assert next(a for a in listing.json() if a["kind"] == "google")["configured"] is False


async def test_the_secret_is_never_returned(api: AsyncClient, staff: dict[str, str]) -> None:
    """Write-only, like every other credential on this platform."""
    saved = await api.put(
        "/api/v1/platform/oauth-apps/google",
        json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        headers=staff,
    )
    listing = await api.get("/api/v1/platform/oauth-apps", headers=staff)

    for body in (saved.json(), listing.json()):
        assert CLIENT_SECRET not in json.dumps(body)

    assert saved.json()["secret_last4"] == CLIENT_SECRET[-4:]


async def test_a_company_admin_cannot_reach_the_platform_setting(
    api: AsyncClient, session: AsyncSession
) -> None:
    """One app serves every tenant, so one tenant must not own it."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    company = {"Authorization": f"Bearer {acme.admin_token}"}

    for method, path in (
        ("GET", "/api/v1/platform/oauth-apps"),
        ("PUT", "/api/v1/platform/oauth-apps/google"),
        ("PATCH", "/api/v1/platform/oauth-apps/google"),
        ("DELETE", "/api/v1/platform/oauth-apps/google"),
    ):
        response = await api.request(
            method, path, headers=company, json={"client_id": "x", "client_secret": "y"}
        )
        assert response.status_code in (401, 403), f"{method} {path} accepted a company token"


async def test_registering_is_recorded_in_the_audit_log(
    api: AsyncClient, staff: dict[str, str]
) -> None:
    await api.put(
        "/api/v1/platform/oauth-apps/google",
        json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        headers=staff,
    )
    entries = await api.get("/api/v1/platform/audit", headers=staff)
    actions = [e["action"] for e in entries.json()]

    assert "oauth_app_registered" in actions
    # The client id is useful in a diary; the secret never is.
    assert CLIENT_SECRET not in json.dumps(entries.json())
