"""Reading a web page: every address on the way is checked, redirects too."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx
import pytest

from app.agent.tools import ToolContext, registry

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def fake_web(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], list[str]]:
    import app.agent.tools.packs.web as web

    real_client = httpx.AsyncClient

    def install(handler: Handler) -> list[str]:
        seen: list[str] = []

        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return handler(request)

        monkeypatch.setattr(
            web.httpx,
            "AsyncClient",
            lambda **kw: real_client(transport=httpx.MockTransport(recording), **kw),
        )
        # "internal.test" stands in for an address inside the network.
        monkeypatch.setattr(web, "_is_private_address", lambda host: host == "internal.test")
        return seen

    return install


async def _read(url: str) -> object:
    tool = registry.get("get_webpage")
    assert tool is not None
    return await tool().execute(ToolContext(owner_id=uuid.uuid4()), {"url": url})


async def test_a_public_page_is_read_as_text(fake_web: Callable[[Handler], list[str]]) -> None:
    fake_web(
        lambda r: httpx.Response(
            200, text="<h1>Hello</h1><p>World</p>", headers={"content-type": "text/html"}
        )
    )
    result = await _read("https://example.com/")
    assert result.ok, result.message  # type: ignore[attr-defined]
    assert "Hello" in result.data["content"]  # type: ignore[attr-defined]


async def test_a_redirect_into_the_private_network_is_refused(
    fake_web: Callable[[Handler], list[str]],
) -> None:
    seen = fake_web(
        lambda r: httpx.Response(302, headers={"location": "http://internal.test/admin"})
    )
    result = await _read("https://example.com/go")
    assert not result.ok  # type: ignore[attr-defined]
    assert result.error_class == "not_allowed"  # type: ignore[attr-defined]
    assert seen == ["https://example.com/go"]  # the internal address was never called


async def test_a_safe_redirect_is_followed(fake_web: Callable[[Handler], list[str]]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text="moved here")

    seen = fake_web(handler)
    result = await _read("https://example.com/old")
    assert result.ok and result.data["content"] == "moved here"  # type: ignore[attr-defined]
    assert seen == ["https://example.com/old", "https://example.com/new"]


async def test_endless_redirects_stop(fake_web: Callable[[Handler], list[str]]) -> None:
    fake_web(lambda r: httpx.Response(302, headers={"location": "/again"}))
    result = await _read("https://example.com/loop")
    assert not result.ok and "too many" in result.message  # type: ignore[attr-defined]
