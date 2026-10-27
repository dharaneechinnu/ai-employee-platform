"""A search key is a provider the person brings, like an AI key."""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_person


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_search(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Tavily and Brave answer from here: good key `good-key-123`, anything else is refused."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        auth = request.headers.get("authorization", "") + request.headers.get(
            "x-subscription-token", ""
        )
        if "good-key-123" not in auth:
            return httpx.Response(401, json={})
        if "tavily" in request.url.host:
            return httpx.Response(
                200, json={"results": [{"title": "T", "url": "u", "content": "c"}]}
            )
        return httpx.Response(200, json={"web": {"results": [{"title": "B", "url": "u"}]}})

    real = httpx.AsyncClient

    def client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("app.agent.tools.packs.search.httpx.AsyncClient", client)
    return seen


async def test_search_providers_are_listed_apart_from_ais(
    api: AsyncClient, session: AsyncSession
) -> None:
    me = await seed_person(session, api)
    ais = (await api.get("/api/v1/me/providers/available", headers=_h(me.token))).json()
    search = (
        await api.get("/api/v1/me/providers/available?kind=search", headers=_h(me.token))
    ).json()
    assert {"tavily", "brave"}.isdisjoint(p["key"] for p in ais)
    assert {p["key"] for p in search} == {"tavily", "brave"}
    assert all(len(p["guide"]) >= 3 for p in search)
    gemini = next(p for p in ais if p["key"] == "gemini")
    assert gemini["free_tier"] is True and gemini["recommended_rank"] == 1


async def test_a_search_key_connects_tests_and_never_becomes_an_ai(
    api: AsyncClient, session: AsyncSession, fake_search: list[httpx.Request]
) -> None:
    me = await seed_person(session, api)
    h = _h(me.token)
    res = await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "tavily", "api_key": "good-key-123"},
        headers=h,
    )
    assert res.status_code == 201 and res.json()["key_last4"] == "-123"

    tested = await api.post("/api/v1/me/providers/tavily/test", headers=h)
    assert tested.json()["status"] == "working"

    assert (await api.get("/api/v1/me/providers", headers=h)).json() == []
    kept = (await api.get("/api/v1/me/providers?kind=search", headers=h)).json()
    assert [p["provider_key"] for p in kept] == ["tavily"]
    assert (await api.get("/api/v1/me/models", headers=h)).json() == []

    # A search key does not count as picking an AI.
    setup = (await api.get("/api/v1/me/setup", headers=h)).json()
    assert setup["done"] == []

    # And it cannot be asked for models.
    assert (await api.get("/api/v1/me/providers/tavily/models", headers=h)).status_code == 422


async def test_a_refused_search_key_fails_its_test(
    api: AsyncClient, session: AsyncSession, fake_search: list[httpx.Request]
) -> None:
    me = await seed_person(session, api)
    h = _h(me.token)
    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "brave", "api_key": "wrong-key-999"},
        headers=h,
    )
    tested = (await api.post("/api/v1/me/providers/brave/test", headers=h)).json()
    assert tested["status"] == "failed" and "refused" in tested["last_error"]


async def test_the_web_search_tool_uses_the_persons_key_first(
    api: AsyncClient, session: AsyncSession, fake_search: list[httpx.Request]
) -> None:
    from app.agent.tools.base import ToolContext
    from app.agent.tools.packs.search import WebSearch, WebSearchArgs

    me = await seed_person(session, api)
    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "tavily", "api_key": "good-key-123"},
        headers=_h(me.token),
    )
    ctx = ToolContext(owner_id=me.owner_id, config={"_session": session})
    result = await WebSearch().run(ctx, WebSearchArgs(query="events in chennai"))
    assert result.ok and result.data["results"][0]["title"] == "T"
    assert "tavily" in fake_search[-1].url.host


async def test_with_no_key_anywhere_the_tool_says_how_to_fix_it(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agent.tools.base import ToolContext
    from app.agent.tools.packs.search import WebSearch, WebSearchArgs
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "tavily_api_key", None)
    monkeypatch.setattr(get_settings(), "brave_api_key", None)
    me = await seed_person(session, api)
    ctx = ToolContext(owner_id=me.owner_id, config={"_session": session})
    result = await WebSearch().run(ctx, WebSearchArgs(query="events in chennai"))
    assert not result.ok and "AI keys" in (result.message or "")
