"""A key's models are found and checked for it, not assumed.

The provider is faked, so what is tested is the platform's behaviour:
it skips models the plan cannot reach, stops on a bad key, and never
offers a model that cannot chat.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.providers.base import (
    LLMProvider,
    ProviderAuthError,
    ProviderModelNotFoundError,
)
from tests.integration.conftest import seed_person

LISTED = [
    "text-embedding-004",
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


class FakeProvider(LLMProvider):
    provider_key = "gemini"
    reachable: ClassVar[set[str]] = set()
    key_ok = True
    asked: ClassVar[list[str]] = []

    async def complete(self, **kwargs: Any) -> Any:  # pragma: no cover - not used
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        return list(LISTED)

    async def check(self, model: str) -> None:
        FakeProvider.asked.append(model)
        if not FakeProvider.key_ok:
            raise ProviderAuthError("rejected", status_code=401)
        if model not in FakeProvider.reachable:
            raise ProviderModelNotFoundError("not on this plan", status_code=404)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> type[FakeProvider]:
    import app.services.provider_service as svc

    FakeProvider.reachable = {"gemini-2.0-flash"}
    FakeProvider.key_ok = True
    FakeProvider.asked = []
    monkeypatch.setattr(svc, "build_provider", lambda key, api_key, **_: FakeProvider(api_key))
    return FakeProvider


async def _connected(api: AsyncClient, session: AsyncSession) -> dict[str, str]:
    person = await seed_person(session, api, name="Asha")
    headers = {"Authorization": f"Bearer {person.token}"}
    made = await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "gemini", "api_key": "test-key-abcd1234"},
        headers=headers,
    )
    assert made.status_code == 201, made.text
    return headers


async def test_the_model_list_only_offers_models_that_can_chat(
    api: AsyncClient, session: AsyncSession, fake: type[FakeProvider]
) -> None:
    headers = await _connected(api, session)
    listed = await api.get("/api/v1/me/providers/gemini/models", headers=headers)
    assert "text-embedding-004" not in listed.json()
    assert "gemini-2.0-flash" in listed.json()


async def test_it_skips_models_the_plan_cannot_reach_and_picks_one_that_works(
    api: AsyncClient, session: AsyncSession, fake: type[FakeProvider]
) -> None:
    headers = await _connected(api, session)
    done = await api.post("/api/v1/me/providers/gemini/auto-model", headers=headers)
    assert done.status_code == 200, done.text
    body = done.json()

    assert body["selected"] == "gemini-2.0-flash"
    assert body["provider"]["default_model"] == "gemini-2.0-flash"
    assert body["provider"]["status"] == "working"
    # The stable models were tried before the preview, and the one that
    # failed says why, in words a person can act on.
    failed = [t for t in body["tried"] if not t["ok"]]
    assert all("plan" in t["reason"] for t in failed)
    assert "gemini-2.5-pro-preview-05-06" not in fake.asked[:1]


async def test_a_rejected_key_stops_at_once_and_is_marked_failed(
    api: AsyncClient, session: AsyncSession, fake: type[FakeProvider]
) -> None:
    headers = await _connected(api, session)
    fake.key_ok = False
    body = (await api.post("/api/v1/me/providers/gemini/auto-model", headers=headers)).json()

    assert body["selected"] is None
    assert len(fake.asked) == 1  # no point trying more models with a bad key
    assert body["provider"]["status"] == "failed"


async def test_when_nothing_works_the_current_model_is_left_alone(
    api: AsyncClient, session: AsyncSession, fake: type[FakeProvider]
) -> None:
    headers = await _connected(api, session)
    fake.reachable = set()
    before = (await api.get("/api/v1/me/providers", headers=headers)).json()[0]["default_model"]
    body = (await api.post("/api/v1/me/providers/gemini/auto-model", headers=headers)).json()

    assert body["selected"] is None
    assert body["provider"]["default_model"] == before
    assert len(body["tried"]) <= 4


async def test_another_person_cannot_run_it_on_my_provider(
    api: AsyncClient, session: AsyncSession, fake: type[FakeProvider]
) -> None:
    await _connected(api, session)
    other = await seed_person(session, api)
    theirs = {"Authorization": f"Bearer {other.token}"}
    # They have no such provider connected, so there is nothing to find.
    assert (
        await api.post("/api/v1/me/providers/gemini/auto-model", headers=theirs)
    ).status_code == 404


async def test_another_provider_can_be_connected_without_naming_a_model(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import urls

    monkeypatch.setattr(urls, "is_private_address", lambda host: False)
    """The person knows the provider and the key: that is enough. The
    model is found afterwards, or asked for."""
    person = await seed_person(session, api, name="Asha")
    headers = {"Authorization": f"Bearer {person.token}"}
    made = await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "custom", "base_url": "https://llm.acme.com/v1", "api_key": ""},
        headers=headers,
    )
    assert made.status_code == 201, made.text


async def test_sarvam_is_in_the_provider_menu(api: AsyncClient, session: AsyncSession) -> None:
    person = await seed_person(session, api, name="Asha")
    headers = {"Authorization": f"Bearer {person.token}"}
    menu = await api.get("/api/v1/me/providers/available", headers=headers)
    assert "sarvam" in [p["key"] for p in menu.json()]
