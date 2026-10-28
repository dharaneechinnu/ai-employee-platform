"""A person switching one-click sign-in on for itself.

The platform can register one Google app that every person signs in
through, but that puts the operator in the critical path of every
customer's setup. A person can instead register its own app, in its
own Google Cloud project, with its own name on the consent screen.

Resolution is person, then platform, then environment — so a person
that does nothing still gets the platform's app, and a person that
registers its own is not overridden by it.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_person

OWN_ID = "555-acme-own.apps.googleusercontent.com"
OWN_SECRET = "GOCSPX-acme-own-secret-8kL2"

PLATFORM_ID = "111-platform.apps.googleusercontent.com"
PLATFORM_SECRET = "GOCSPX-platform-secret-4421"


async def _platform_token(api: AsyncClient, session: AsyncSession) -> str:
    from app.services.platform_service import PlatformService

    email, password = "staff@platformco.com", "platform-admin-password"
    await PlatformService(session).create_admin(email=email, password=password)
    await session.commit()

    response = await api.post(
        "/api/v1/platform/auth/login", json={"email": email, "password": password}
    )
    return str(response.json()["access_token"])


@pytest.fixture
async def staff(api: AsyncClient, session: AsyncSession) -> dict[str, str]:
    return {"Authorization": f"Bearer {await _platform_token(api, session)}"}


async def _google(api: AsyncClient, owner_id: object, headers: dict[str, str]) -> dict:
    listing = await api.get("/api/v1/me/connections/available", headers=headers)
    return next(a for a in listing.json() if a["kind"] == "google")


async def _client_id_in_use(api: AsyncClient, owner_id: object, headers: dict[str, str]) -> str:
    from urllib.parse import parse_qs, urlparse

    start = await api.post("/api/v1/me/connections/oauth/google/start", headers=headers)
    query = parse_qs(urlparse(start.json()["authorize_url"]).query)
    return str(query["client_id"][0])


async def test_a_person_can_switch_one_click_on_by_itself(
    api: AsyncClient, session: AsyncSession
) -> None:
    """No platform admin involved at any point in this test."""
    acme = await seed_person(session, api, name="Acme")
    headers = {"Authorization": f"Bearer {acme.token}"}

    assert (await _google(api, acme.owner_id, headers))["configured"] is False

    saved = await api.put(
        "/api/v1/me/connections/oauth-apps/google",
        json={"client_id": OWN_ID, "client_secret": OWN_SECRET},
        headers=headers,
    )
    assert saved.status_code == 200
    # The redirect address comes back, because it has to go into
    # Google's console and must match to the character.
    assert saved.json()["redirect_uri"].endswith("/oauth/google/callback")

    assert (await _google(api, acme.owner_id, headers))["configured"] is True
    assert await _client_id_in_use(api, acme.owner_id, headers) == OWN_ID


async def test_a_persons_own_app_wins_over_the_platforms(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    """Registering one is deliberate, so it outranks the shared app."""
    acme = await seed_person(session, api, name="Acme")
    other = await seed_person(session, api, name="Globex")
    acme_h = {"Authorization": f"Bearer {acme.token}"}
    other_h = {"Authorization": f"Bearer {other.token}"}

    await api.put(
        "/api/v1/platform/oauth-apps/google",
        json={"client_id": PLATFORM_ID, "client_secret": PLATFORM_SECRET},
        headers=staff,
    )
    await api.put(
        "/api/v1/me/connections/oauth-apps/google",
        json={"client_id": OWN_ID, "client_secret": OWN_SECRET},
        headers=acme_h,
    )

    assert await _client_id_in_use(api, acme.owner_id, acme_h) == OWN_ID
    # The person that did nothing still gets the platform's app.
    assert await _client_id_in_use(api, other.owner_id, other_h) == PLATFORM_ID


async def test_removing_our_own_app_falls_back_to_the_platforms(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    acme = await seed_person(session, api, name="Acme")
    headers = {"Authorization": f"Bearer {acme.token}"}

    await api.put(
        "/api/v1/platform/oauth-apps/google",
        json={"client_id": PLATFORM_ID, "client_secret": PLATFORM_SECRET},
        headers=staff,
    )
    await api.put(
        "/api/v1/me/connections/oauth-apps/google",
        json={"client_id": OWN_ID, "client_secret": OWN_SECRET},
        headers=headers,
    )
    assert await _client_id_in_use(api, acme.owner_id, headers) == OWN_ID

    removed = await api.delete("/api/v1/me/connections/oauth-apps/google", headers=headers)
    assert removed.status_code == 204
    assert await _client_id_in_use(api, acme.owner_id, headers) == PLATFORM_ID


async def test_one_persons_app_is_invisible_to_another(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_person(session, api, name="Acme")
    other = await seed_person(session, api, name="Globex")

    await api.put(
        "/api/v1/me/connections/oauth-apps/google",
        json={"client_id": OWN_ID, "client_secret": OWN_SECRET},
        headers={"Authorization": f"Bearer {acme.token}"},
    )

    listing = await api.get(
        "/api/v1/me/connections/oauth-apps",
        headers={"Authorization": f"Bearer {other.token}"},
    )
    assert listing.json() == []
    assert (await _google(api, other.owner_id, {"Authorization": f"Bearer {other.token}"}))[
        "configured"
    ] is False


async def test_the_secret_is_never_returned(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_person(session, api, name="Acme")
    headers = {"Authorization": f"Bearer {acme.token}"}

    saved = await api.put(
        "/api/v1/me/connections/oauth-apps/google",
        json={"client_id": OWN_ID, "client_secret": OWN_SECRET},
        headers=headers,
    )
    listing = await api.get("/api/v1/me/connections/oauth-apps", headers=headers)

    for body in (saved.json(), listing.json()):
        assert OWN_SECRET not in json.dumps(body)
    assert saved.json()["secret_last4"] == OWN_SECRET[-4:]
