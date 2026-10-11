"""Cross-tenant isolation, exercised through the real API.

The schema-level guard in tests/isolation/ proves every table *has*
org_id. These tests prove the API actually *uses* it.

Both matter. A column nobody filters on protects nothing.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_company


async def test_company_a_cannot_read_company_b_members(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    globex = await seed_company(session, api, name="Globex", slug="globex")

    response = await api.get(
        f"/api/v1/orgs/{globex.org_id}/members",
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )

    # 404, not 403. A 403 would confirm that Globex exists.
    assert response.status_code == 404


async def test_company_a_cannot_invite_into_company_b(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    globex = await seed_company(session, api, name="Globex", slug="globex")

    response = await api.post(
        f"/api/v1/orgs/{globex.org_id}/invites",
        json={"email": "intruder@acme.com", "role": "admin"},
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )
    assert response.status_code == 404


async def test_company_a_cannot_read_company_b_details(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    globex = await seed_company(session, api, name="Globex", slug="globex")

    response = await api.get(
        f"/api/v1/orgs/{globex.org_id}",
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )
    assert response.status_code == 404


async def test_cross_tenant_and_nonexistent_are_indistinguishable(
    api: AsyncClient, session: AsyncSession
) -> None:
    """The whole point of using 404: a caller cannot tell "not yours"
    apart from "does not exist", so company ids cannot be probed."""
    import uuid

    acme = await seed_company(session, api, name="Acme", slug="acme")
    globex = await seed_company(session, api, name="Globex", slug="globex")
    headers = {"Authorization": f"Bearer {acme.admin_token}"}

    real_but_not_mine = await api.get(f"/api/v1/orgs/{globex.org_id}/members", headers=headers)
    never_existed = await api.get(f"/api/v1/orgs/{uuid.uuid4()}/members", headers=headers)

    assert real_but_not_mine.status_code == never_existed.status_code == 404
    assert real_but_not_mine.json() == never_existed.json()


async def test_member_cannot_invite(api: AsyncClient, session: AsyncSession) -> None:
    """Admin builds, Member uses. Inviting is a build action."""
    acme = await seed_company(session, api, name="Acme", slug="acme")

    response = await api.post(
        f"/api/v1/orgs/{acme.org_id}/invites",
        json={"email": "friend@acme.com", "role": "member"},
        headers={"Authorization": f"Bearer {acme.member_token}"},
    )
    # 403 here, not 404: they ARE a member of this company, so the
    # resource's existence is not a secret from them. Only the action
    # is denied.
    assert response.status_code == 403


async def test_member_can_read_members(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")

    response = await api.get(
        f"/api/v1/orgs/{acme.org_id}/members",
        headers={"Authorization": f"Bearer {acme.member_token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_member_cannot_change_roles(api: AsyncClient, session: AsyncSession) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")

    members = await api.get(
        f"/api/v1/orgs/{acme.org_id}/members",
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )
    member_id = next(m["id"] for m in members.json() if m["role"] == "member")

    response = await api.patch(
        f"/api/v1/orgs/{acme.org_id}/members/{member_id}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {acme.member_token}"},
    )
    assert response.status_code == 403
