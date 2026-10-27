"""The setup bar's data: ticked by what exists, saved, and never taken back."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.db.models.provider import ConnectionStatus, ProviderConfig
from tests.integration.conftest import seed_person


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _add_key(session: AsyncSession, owner_id, status: ConnectionStatus) -> None:  # type: ignore[no-untyped-def]
    session.add(
        ProviderConfig(
            owner_id=owner_id,
            provider_key="groq",
            api_key_enc=encrypt("gsk_test_key_0001", scope=owner_id),
            key_last4="0001",
            status=status,
        )
    )
    await session.commit()


async def test_new_person_starts_at_the_first_step(api: AsyncClient, session: AsyncSession) -> None:
    me = await seed_person(session, api)
    res = await api.get("/api/v1/me/setup", headers=_auth(me.token))
    assert res.status_code == 200
    body = res.json()
    assert body["done"] == []
    assert body["next_step"] == "pick_ai"
    assert body["complete"] is False
    assert body["steps"] == ["pick_ai", "add_key", "connect_app", "first_agent"]


async def test_untested_key_ticks_only_step_one(api: AsyncClient, session: AsyncSession) -> None:
    me = await seed_person(session, api)
    await _add_key(session, me.owner_id, ConnectionStatus.UNTESTED)
    body = (await api.get("/api/v1/me/setup", headers=_auth(me.token))).json()
    assert body["done"] == ["pick_ai"]
    assert body["next_step"] == "add_key"


async def test_working_key_ticks_two_and_a_tick_is_never_taken_back(
    api: AsyncClient, session: AsyncSession
) -> None:
    me = await seed_person(session, api)
    await _add_key(session, me.owner_id, ConnectionStatus.WORKING)
    body = (await api.get("/api/v1/me/setup", headers=_auth(me.token))).json()
    assert body["done"] == ["pick_ai", "add_key"]
    assert body["next_step"] == "connect_app"

    await session.execute(delete(ProviderConfig).where(ProviderConfig.owner_id == me.owner_id))
    await session.commit()
    again = (await api.get("/api/v1/me/setup", headers=_auth(me.token))).json()
    assert again["done"] == ["pick_ai", "add_key"]


async def test_guide_steps_are_saved_once(api: AsyncClient, session: AsyncSession) -> None:
    me = await seed_person(session, api)
    for _ in range(2):
        res = await api.post(
            "/api/v1/me/setup/guide",
            headers=_auth(me.token),
            json={"provider": "groq", "step": "signup"},
        )
        assert res.status_code == 200
    body = (await api.get("/api/v1/me/setup", headers=_auth(me.token))).json()
    assert body["guide"] == {"groq": ["signup"]}


async def test_progress_is_private_to_the_person(api: AsyncClient, session: AsyncSession) -> None:
    a = await seed_person(session, api)
    b = await seed_person(session, api)
    await _add_key(session, a.owner_id, ConnectionStatus.WORKING)
    mine = (await api.get("/api/v1/me/setup", headers=_auth(a.token))).json()
    theirs = (await api.get("/api/v1/me/setup", headers=_auth(b.token))).json()
    assert mine["done"] == ["pick_ai", "add_key"]
    assert theirs["done"] == []


async def test_setup_needs_sign_in(api: AsyncClient) -> None:
    assert (await api.get("/api/v1/me/setup")).status_code == 401
