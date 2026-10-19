"""Platform Admin: the normal path.

Create an admin, sign in with 2FA, create a company, hand its invite to
the first user, and set the employee limit.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_admin(session: AsyncSession) -> tuple[str, str]:
    """Returns (email, password)."""
    from app.services.platform_service import PlatformService

    email, password = "root@platform.com", "platform-admin-password"
    await PlatformService(session).create_admin(email=email, password=password)
    await session.commit()
    return email, password


async def _sign_in(api: AsyncClient, email: str, password: str) -> str:
    response = await api.post(
        "/api/v1/platform/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def test_platform_admin_can_sign_in(api: AsyncClient, session: AsyncSession) -> None:
    email, password = await _make_admin(session)
    assert await _sign_in(api, email, password)


async def test_a_wrong_password_is_refused(api: AsyncClient, session: AsyncSession) -> None:
    """The only thing guarding this account now that 2FA is gone.

    Worth a test of its own precisely because it is the whole gate: a
    Platform Admin can create and suspend every company, and there is
    no second factor behind this check any more.
    """
    email, _ = await _make_admin(session)

    response = await api.post(
        "/api/v1/platform/auth/login",
        json={"email": email, "password": "not-the-password"},
    )
    assert response.status_code == 401


async def test_create_an_account_and_let_its_owner_set_a_password(
    api: AsyncClient, session: AsyncSession
) -> None:
    email, password = await _make_admin(session)
    token = await _sign_in(api, email, password)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        "/api/v1/platform/people",
        json={"email": "owner@victopia.com", "max_employees": 5},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["max_employees"] == 5

    # The setup link is returned once. The owner sets their own
    # password through it, so the Platform Admin never knows one.
    accepted = await api.post(
        "/api/v1/auth/setup",
        json={"token": body["setup_token"], "password": "owner-password-123"},
    )
    assert accepted.status_code == 201

    me = await api.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {accepted.json()['access_token']}"},
    )
    assert me.json()["email"] == "owner@victopia.com"
    assert me.json()["max_employees"] == 5


async def test_list_people_shows_counts(api: AsyncClient, session: AsyncSession) -> None:
    email, password = await _make_admin(session)
    token = await _sign_in(api, email, password)
    headers = {"Authorization": f"Bearer {token}"}

    await api.post(
        "/api/v1/platform/people",
        json={"email": "owner@acme.com", "max_employees": 3},
        headers=headers,
    )

    listed = await api.get("/api/v1/platform/people", headers=headers)
    assert listed.status_code == 200
    row = next(r for r in listed.json() if r["email"] == "owner@acme.com")
    assert row["max_employees"] == 3
    assert row["employees_used"] == 0
    assert row["active"] is True


async def test_change_employee_limit(api: AsyncClient, session: AsyncSession) -> None:
    email, password = await _make_admin(session)
    token = await _sign_in(api, email, password)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        "/api/v1/platform/people",
        json={"email": "owner@acme.com", "max_employees": 3},
        headers=headers,
    )
    owner_id = created.json()["id"]

    updated = await api.patch(
        f"/api/v1/platform/people/{owner_id}/limits",
        json={"max_employees": 10},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["max_employees"] == 10


async def test_suspend_and_restore_an_account(api: AsyncClient, session: AsyncSession) -> None:
    email, password = await _make_admin(session)
    token = await _sign_in(api, email, password)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        "/api/v1/platform/people",
        json={"email": "owner@acme.com", "max_employees": 3},
        headers=headers,
    )
    owner_id = created.json()["id"]

    suspended = await api.post(f"/api/v1/platform/people/{owner_id}/suspend", headers=headers)
    assert suspended.json()["active"] is False

    restored = await api.post(f"/api/v1/platform/people/{owner_id}/restore", headers=headers)
    assert restored.json()["active"] is True


async def test_a_customer_token_cannot_reach_platform_routes(
    api: AsyncClient, session: AsyncSession
) -> None:
    """The one security test worth keeping here. A Company Admin token
    carries typ=access, not typ=platform_access, so it is refused even
    though its holder is an admin of their own company."""
    from tests.integration.conftest import seed_company

    company = await seed_company(session, api, name="Acme", slug="acme")

    response = await api.get(
        "/api/v1/platform/people",
        headers={"Authorization": f"Bearer {company.admin_token}"},
    )
    assert response.status_code == 401


async def test_the_list_counts_each_persons_employees(
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
            "/api/v1/me/ai-employees",
            json={"name": f"Bot {i}", "config": {"guided": {"what_it_does": "work"}}},
            headers=headers,
        )
        assert created.status_code == 201

    email, password = await _make_admin(session)
    token = await _sign_in(api, email, password)

    listed = await api.get(
        "/api/v1/platform/people", headers={"Authorization": f"Bearer {token}"}
    )
    row = next(r for r in listed.json() if r["email"] == acme.email)

    assert row["employees_used"] == 3
