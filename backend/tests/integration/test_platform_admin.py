"""Platform Admin: the normal path.

Create an admin, sign in with 2FA, create a company, hand its invite to
the first user, and set the employee limit.
"""

from __future__ import annotations

import pyotp
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_admin(session: AsyncSession) -> tuple[str, str, str]:
    """Returns (email, password, totp_secret)."""
    from app.services.platform_service import PlatformService

    email, password = "root@platform.com", "platform-admin-password"
    _, secret = await PlatformService(session).create_admin(email=email, password=password)
    await session.commit()
    return email, password, secret


async def _sign_in(api: AsyncClient, email: str, password: str, secret: str) -> str:
    response = await api.post(
        "/api/v1/platform/auth/login",
        json={"email": email, "password": password, "totp_code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def test_platform_admin_can_sign_in_with_2fa(api: AsyncClient, session: AsyncSession) -> None:
    email, password, secret = await _make_admin(session)
    token = await _sign_in(api, email, password, secret)
    assert token


async def test_login_without_the_totp_code_is_refused(
    api: AsyncClient, session: AsyncSession
) -> None:
    """2FA is compulsory: this account governs every company, so a
    leaked password alone must not be enough."""
    email, password, _ = await _make_admin(session)

    response = await api.post(
        "/api/v1/platform/auth/login",
        json={"email": email, "password": password, "totp_code": "000000"},
    )
    assert response.status_code == 401


async def test_create_company_and_onboard_its_first_admin(
    api: AsyncClient, session: AsyncSession
) -> None:
    email, password, secret = await _make_admin(session)
    token = await _sign_in(api, email, password, secret)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        "/api/v1/platform/companies",
        json={
            "name": "Victopia Labs",
            "slug": "victopia",
            "first_admin_email": "owner@victopia.com",
            "max_employees": 5,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["max_employees"] == 5

    # The invite token is returned once; the new admin uses it to join.
    accepted = await api.post(
        "/api/v1/auth/accept-invite",
        json={"token": body["invite_token"], "password": "owner-password-123"},
    )
    assert accepted.status_code == 201

    me = await api.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {accepted.json()['access_token']}"},
    )
    assert me.json()["organizations"][0]["role"] == "admin"


async def test_list_companies_shows_counts(api: AsyncClient, session: AsyncSession) -> None:
    email, password, secret = await _make_admin(session)
    token = await _sign_in(api, email, password, secret)
    headers = {"Authorization": f"Bearer {token}"}

    await api.post(
        "/api/v1/platform/companies",
        json={
            "name": "Acme",
            "slug": "acme",
            "first_admin_email": "owner@acme.com",
            "max_employees": 3,
        },
        headers=headers,
    )

    listed = await api.get("/api/v1/platform/companies", headers=headers)
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["slug"] == "acme"
    assert row["max_employees"] == 3
    assert "member_count" in row


async def test_change_employee_limit(api: AsyncClient, session: AsyncSession) -> None:
    email, password, secret = await _make_admin(session)
    token = await _sign_in(api, email, password, secret)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        "/api/v1/platform/companies",
        json={
            "name": "Acme",
            "slug": "acme",
            "first_admin_email": "owner@acme.com",
            "max_employees": 3,
        },
        headers=headers,
    )
    org_id = created.json()["id"]

    updated = await api.patch(
        f"/api/v1/platform/companies/{org_id}/limits",
        json={"max_employees": 10},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["max_employees"] == 10


async def test_suspend_a_company(api: AsyncClient, session: AsyncSession) -> None:
    email, password, secret = await _make_admin(session)
    token = await _sign_in(api, email, password, secret)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        "/api/v1/platform/companies",
        json={
            "name": "Acme",
            "slug": "acme",
            "first_admin_email": "owner@acme.com",
            "max_employees": 3,
        },
        headers=headers,
    )
    org_id = created.json()["id"]

    suspended = await api.post(f"/api/v1/platform/companies/{org_id}/suspend", headers=headers)
    assert suspended.json()["status"] == "suspended"

    reactivated = await api.post(f"/api/v1/platform/companies/{org_id}/reactivate", headers=headers)
    assert reactivated.json()["status"] == "active"


async def test_a_customer_token_cannot_reach_platform_routes(
    api: AsyncClient, session: AsyncSession
) -> None:
    """The one security test worth keeping here. A Company Admin token
    carries typ=access, not typ=platform_access, so it is refused even
    though its holder is an admin of their own company."""
    from tests.integration.conftest import seed_company

    company = await seed_company(session, api, name="Acme", slug="acme")

    response = await api.get(
        "/api/v1/platform/companies",
        headers={"Authorization": f"Bearer {company.admin_token}"},
    )
    assert response.status_code == 401


async def test_company_list_counts_members_and_employees_independently(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Counting both in one query multiplies the rows together.

    A company with 2 members and 3 AI Employees would report 6 of each.
    This caught a real bug where the list always showed 0 employees
    while the detail view showed the right number.
    """
    from tests.integration.conftest import seed_company

    acme = await seed_company(session, api, name="Acme", slug="acme")  # 2 members
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    for i in range(3):
        created = await api.post(
            f"/api/v1/orgs/{acme.org_id}/ai-employees",
            json={"name": f"Bot {i}", "config": {"guided": {"what_it_does": "work"}}},
            headers=headers,
        )
        assert created.status_code == 201

    email, password, secret = await _make_admin(session)
    token = await _sign_in(api, email, password, secret)

    listed = await api.get(
        "/api/v1/platform/companies", headers={"Authorization": f"Bearer {token}"}
    )
    row = next(r for r in listed.json() if r["slug"] == "acme")

    assert row["member_count"] == 2
    assert row["employees_used"] == 3
