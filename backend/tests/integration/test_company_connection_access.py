"""Which connections one company may use.

Registering an OAuth app decides whether a connection exists on the
platform at all. This decides whether a *particular* company may use
it — a customer whose plan excludes database access, say — without
taking it away from everyone.

Absence of a ruling means inherit, so the table starts empty and
nothing changed for companies already connected.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_company


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


DB_CONNECTION = {
    "kind": "database",
    "label": "Reporting",
    "secret": "postgresql://reader:secret@db.internal:5432/reports",
    "config": {
        "host": "db.internal",
        "port": 5432,
        "database": "reports",
        "username": "reader",
    },
}


async def _available(api: AsyncClient, org_id: object, headers: dict[str, str], kind: str) -> dict:
    listing = await api.get(f"/api/v1/orgs/{org_id}/connections/available", headers=headers)
    return next(a for a in listing.json() if a["kind"] == kind)


async def test_everything_is_open_until_someone_says_otherwise(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")

    rows = await api.get(f"/api/v1/platform/companies/{acme.org_id}/connections", headers=staff)
    assert rows.status_code == 200
    for row in rows.json():
        assert row["allowed"] is True
        # Not the same as "explicitly opened": nothing has been decided.
        assert row["overridden"] is False


async def test_closing_one_connection_for_one_company(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    other = await seed_company(session, api, name="Globex", slug="globex")
    acme_admin = {"Authorization": f"Bearer {acme.admin_token}"}
    other_admin = {"Authorization": f"Bearer {other.admin_token}"}

    closed = await api.put(
        f"/api/v1/platform/companies/{acme.org_id}/connections/database",
        json={"allowed": False, "note": "Not included on your plan."},
        headers=staff,
    )
    assert closed.status_code == 200

    acme_db = await _available(api, acme.org_id, acme_admin, "database")
    assert acme_db["allowed"] is False
    assert acme_db["blocked_note"] == "Not included on your plan."

    # The ruling is about one company, not the connection itself.
    other_db = await _available(api, other.org_id, other_admin, "database")
    assert other_db["allowed"] is True


async def test_a_closed_connection_cannot_be_created_anyway(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    """A greyed-out button is a courtesy; this is the control."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    acme_admin = {"Authorization": f"Bearer {acme.admin_token}"}

    allowed = await api.post(
        f"/api/v1/orgs/{acme.org_id}/connections", json=DB_CONNECTION, headers=acme_admin
    )
    assert allowed.status_code == 201

    await api.put(
        f"/api/v1/platform/companies/{acme.org_id}/connections/database",
        json={"allowed": False, "note": "Not included on your plan."},
        headers=staff,
    )

    refused = await api.post(
        f"/api/v1/orgs/{acme.org_id}/connections", json=DB_CONNECTION, headers=acme_admin
    )
    # Forbidden, not unprocessable: the request is fine, the company is not.
    assert refused.status_code == 403
    assert "plan" in refused.text.lower()


async def test_returning_a_company_to_the_platform_default(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    """Three states, not two: a ruling can be withdrawn."""
    acme = await seed_company(session, api, name="Acme", slug="acme")

    await api.put(
        f"/api/v1/platform/companies/{acme.org_id}/connections/database",
        json={"allowed": False},
        headers=staff,
    )
    back = await api.put(
        f"/api/v1/platform/companies/{acme.org_id}/connections/database",
        json={"allowed": None},
        headers=staff,
    )

    row = next(r for r in back.json() if r["kind"] == "database")
    assert row["allowed"] is True
    assert row["overridden"] is False


async def test_a_company_cannot_open_a_connection_for_itself(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Otherwise the ruling would be advice rather than a control."""
    acme = await seed_company(session, api, name="Acme", slug="acme")
    acme_admin = {"Authorization": f"Bearer {acme.admin_token}"}

    for method, path in (
        ("GET", f"/api/v1/platform/companies/{acme.org_id}/connections"),
        ("PUT", f"/api/v1/platform/companies/{acme.org_id}/connections/database"),
    ):
        response = await api.request(method, path, headers=acme_admin, json={"allowed": True})
        assert response.status_code in (401, 403), f"{method} {path} accepted a company token"


async def test_the_decision_is_recorded(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")

    await api.put(
        f"/api/v1/platform/companies/{acme.org_id}/connections/database",
        json={"allowed": False},
        headers=staff,
    )
    entries = await api.get("/api/v1/platform/audit", headers=staff)
    assert "connection_blocked" in [e["action"] for e in entries.json()]
