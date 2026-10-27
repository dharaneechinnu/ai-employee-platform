"""A key's plan (free or paid): its default, changing it, and what it does to cost."""

# ruff: noqa: F811  (fixtures are imported, then named as test arguments)

from __future__ import annotations

import uuid
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.task import LLMCall, Task
from tests.integration.conftest import seed_person
from tests.integration.test_agent_schedule import (  # noqa: F401  (fixtures)
    AGENTS,
    _new,
    _person,
    _run_task,
    queued,
    scripted,
)

PROVIDERS = "/api/v1/me/providers"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_a_free_tier_provider_starts_free_and_a_paid_one_starts_unsaid(
    api: AsyncClient, session: AsyncSession
) -> None:
    me = await seed_person(session, api)
    h = _h(me.token)
    gemini = await api.post(
        PROVIDERS, json={"provider_key": "gemini", "api_key": "key-gemini-0001"}, headers=h
    )
    claude = await api.post(
        PROVIDERS, json={"provider_key": "anthropic", "api_key": "key-claude-0001"}, headers=h
    )
    assert gemini.json()["plan"] == "free"
    assert claude.json()["plan"] is None


async def test_the_plan_can_be_changed_and_only_to_free_or_paid(
    api: AsyncClient, session: AsyncSession
) -> None:
    me = await seed_person(session, api)
    h = _h(me.token)
    await api.post(
        PROVIDERS, json={"provider_key": "gemini", "api_key": "key-gemini-0001"}, headers=h
    )
    paid = await api.put(f"{PROVIDERS}/gemini/plan", json={"plan": "paid"}, headers=h)
    assert paid.status_code == 200 and paid.json()["plan"] == "paid"
    listed = (await api.get(PROVIDERS, headers=h)).json()
    assert listed[0]["plan"] == "paid"
    assert (
        await api.put(f"{PROVIDERS}/gemini/plan", json={"plan": "gold"}, headers=h)
    ).status_code == 422
    assert (
        await api.put(f"{PROVIDERS}/groq/plan", json={"plan": "free"}, headers=h)
    ).status_code == 404


async def test_a_run_on_a_free_key_costs_nothing_and_on_a_paid_key_it_costs(
    api: AsyncClient, session: AsyncSession, scripted: None, queued: list[uuid.UUID]
) -> None:
    _, headers = await _person(api, session)  # connects Gemini: starts free
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()

    async def cost_of_a_run() -> Decimal:
        await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)
        await _run_task(queued[-1])
        session.expire_all()
        task = await session.scalar(select(Task).where(Task.id == queued[-1]))
        assert task is not None
        call = await session.scalar(select(LLMCall).order_by(LLMCall.created_at.desc()).limit(1))
        assert call is not None
        return call.cost_usd

    assert await cost_of_a_run() == 0

    await api.put(f"{PROVIDERS}/gemini/plan", json={"plan": "paid"}, headers=headers)
    assert await cost_of_a_run() > 0
