"""A new AI provider is a row, not a release.

The platform has to keep accepting providers that did not exist when it
was written. These tests add one that no code knows about, then connect
a key to it as an ordinary person, and check it is spoken to the way
its row says: right address, right wire format, right auth header.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import urls
from app.db.models.provider import SupportedProvider
from app.services.provider_service import ProviderService
from tests.integration.conftest import seed_person

PROVIDER = {
    "display_name": "Acme AI",
    "base_url": "https://llm.acme.com/v1",
    "api_format": "openai",
    "auth_header": "x-acme-key",
    "default_model": "acme-1",
}


@pytest.fixture(autouse=True)
def _public_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urls, "is_private_address", lambda host: False)


async def _staff(api: AsyncClient, session: AsyncSession) -> dict[str, str]:
    from app.services.platform_service import PlatformService

    await PlatformService(session).create_admin(
        email="staff@platformco.com", password="platform-admin-password"
    )
    await session.commit()
    login = await api.post(
        "/api/v1/platform/auth/login",
        json={"email": "staff@platformco.com", "password": "platform-admin-password"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_a_provider_added_at_runtime_works_for_people_with_no_code_change(
    api: AsyncClient, session: AsyncSession
) -> None:
    staff = await _staff(api, session)
    person = await seed_person(session, api, name="Asha")
    headers = {"Authorization": f"Bearer {person.token}"}

    try:
        before = await api.get("/api/v1/me/providers/available", headers=headers)
        assert "acmeai" not in [p["key"] for p in before.json()]

        added = await api.put("/api/v1/platform/providers/acmeai", json=PROVIDER, headers=staff)
        assert added.status_code == 200, added.text

        menu = await api.get("/api/v1/me/providers/available", headers=headers)
        assert "acmeai" in [p["key"] for p in menu.json()]

        connected = await api.post(
            "/api/v1/me/providers",
            json={"provider_key": "acmeai", "api_key": "acme-secret-key-1234"},
            headers=headers,
        )
        assert connected.status_code == 201, connected.text

        # It is spoken to the way its row says, with no adapter written for it.
        service = ProviderService(session, person.owner_id)
        endpoint = await service.resolve_endpoint("acmeai")
        assert endpoint.base_url == "https://llm.acme.com/v1"
        provider = await service._provider(await service._config("acmeai"))
        assert provider._headers() == {  # type: ignore[attr-defined]
            "Authorization": "Bearer acme-secret-key-1234",
            "x-acme-key": "acme-secret-key-1234",
        }
    finally:
        await session.execute(delete(SupportedProvider).where(SupportedProvider.key == "acmeai"))
        await session.commit()


async def test_a_paused_provider_leaves_the_menu(api: AsyncClient, session: AsyncSession) -> None:
    staff = await _staff(api, session)
    person = await seed_person(session, api)
    headers = {"Authorization": f"Bearer {person.token}"}
    try:
        await api.put("/api/v1/platform/providers/acmeai", json=PROVIDER, headers=staff)
        paused = await api.patch(
            "/api/v1/platform/providers/acmeai", json={"enabled": False}, headers=staff
        )
        assert paused.json()["enabled"] is False
        menu = await api.get("/api/v1/me/providers/available", headers=headers)
        assert "acmeai" not in [p["key"] for p in menu.json()]
    finally:
        await session.execute(delete(SupportedProvider).where(SupportedProvider.key == "acmeai"))
        await session.commit()


async def test_bad_provider_definitions_are_refused(
    api: AsyncClient, session: AsyncSession
) -> None:
    staff = await _staff(api, session)
    bad = [
        ("Not A Key!", PROVIDER),
        ("custom", PROVIDER),  # taken
        ("acmeai", {**PROVIDER, "api_format": "soap"}),
        ("acmeai", {**PROVIDER, "auth_header": "bad header"}),
        ("acmeai", {**PROVIDER, "base_url": "ftp://llm.acme.com"}),
    ]
    for key, body in bad:
        refused = await api.put(f"/api/v1/platform/providers/{key}", json=body, headers=staff)
        assert refused.status_code in (404, 422), (key, refused.text)


async def test_a_person_cannot_edit_the_catalog(api: AsyncClient, session: AsyncSession) -> None:
    person = await seed_person(session, api)
    headers = {"Authorization": f"Bearer {person.token}"}
    response = await api.put("/api/v1/platform/providers/acmeai", json=PROVIDER, headers=headers)
    assert response.status_code in (401, 403)
