"""One person cannot reach another's data, exercised through the real API.

The schema-level guard in tests/isolation/ proves every table *has*
owner_id. These tests prove the API actually *uses* it.

Both matter. A column nobody filters on protects nothing.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_person


async def test_another_persons_conversation_is_not_found(
    api: AsyncClient, session: AsyncSession
) -> None:
    alice = await seed_person(session, api, name="Alice")
    bob = await seed_person(session, api, name="Bob")

    created = await api.post(
        "/api/v1/me/conversations", json={}, headers={"Authorization": f"Bearer {alice.token}"}
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    theirs = await api.get(
        f"/api/v1/me/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {bob.token}"},
    )
    assert theirs.status_code == 404

    listed = await api.get(
        "/api/v1/me/conversations", headers={"Authorization": f"Bearer {bob.token}"}
    )
    assert listed.json() == []


async def test_not_yours_and_nonexistent_are_indistinguishable(
    api: AsyncClient, session: AsyncSession
) -> None:
    """The whole point of using 404: a caller cannot tell "not yours"
    apart from "does not exist", so ids cannot be probed."""
    alice = await seed_person(session, api, name="Alice")
    bob = await seed_person(session, api, name="Bob")

    created = await api.post(
        "/api/v1/me/conversations", json={}, headers={"Authorization": f"Bearer {alice.token}"}
    )
    headers = {"Authorization": f"Bearer {bob.token}"}

    real_but_not_mine = await api.get(
        f"/api/v1/me/conversations/{created.json()['id']}", headers=headers
    )
    never_existed = await api.get(f"/api/v1/me/conversations/{uuid.uuid4()}", headers=headers)

    assert real_but_not_mine.status_code == never_existed.status_code == 404
    assert real_but_not_mine.json() == never_existed.json()
