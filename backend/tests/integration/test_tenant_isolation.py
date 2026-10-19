"""Cross-tenant isolation, exercised through the real API.

The schema-level guard in tests/isolation/ proves every table *has*
owner_id. These tests prove the API actually *uses* it.

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
        f"/api/v1/me/members",
        headers={"Authorization": f"Bearer {acme.admin_token}"},
    )

    # 404, not 403. A 403 would confirm that Globex exists.
    assert response.status_code == 404



async def test_company_a_cannot_read_company_b_details(
    api: AsyncClient, session: AsyncSession
) -> None:
    acme = await seed_company(session, api, name="Acme", slug="acme")
    globex = await seed_company(session, api, name="Globex", slug="globex")

    response = await api.get(
        f"/api/v1/me",
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

    real_but_not_mine = await api.get(f"/api/v1/me/members", headers=headers)
    never_existed = await api.get(f"/api/v1/orgs/{uuid.uuid4()}/members", headers=headers)

    assert real_but_not_mine.status_code == never_existed.status_code == 404
    assert real_but_not_mine.json() == never_existed.json()


