"""Shared test fixtures."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("ENVIRONMENT", "test")
# Tests check the production rule, whatever a developer's .env says.
os.environ["ALLOW_PRIVATE_URLS"] = "false"


@pytest.fixture(autouse=True)
def no_retry_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """A retry after a rate limit waits seconds; no test should."""

    async def instant(seconds: float) -> None:
        return None

    monkeypatch.setattr("app.agent.providers.fallback.pause", instant)


@pytest.fixture(autouse=True)
def no_leftover_rests(monkeypatch: pytest.MonkeyPatch) -> None:
    """An AI resting after a failure is remembered in this process during
    tests, never in a shared Redis (a developer's shell or container may not
    set ENVIRONMENT=test); one test's failures must not route the next test's runs."""
    from app.agent import cooldown

    monkeypatch.setattr(cooldown, "_client", lambda: None)
    cooldown.reset()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client wired directly to the ASGI app — no network, no server."""
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
