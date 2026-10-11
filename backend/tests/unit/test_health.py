"""Health endpoint tests.

/healthz must answer without touching any dependency — that is what
makes it a liveness probe rather than a second readiness probe.
"""

from httpx import AsyncClient


async def test_healthz_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"]


async def test_healthz_does_not_touch_the_database(client: AsyncClient, monkeypatch) -> None:
    """If liveness depended on Postgres, a database blip would restart
    every container instead of just draining traffic."""
    import app.db.session as session_module

    def explode() -> None:
        raise AssertionError("/healthz must not open a database connection")

    monkeypatch.setattr(session_module, "get_engine", explode)

    response = await client.get("/healthz")
    assert response.status_code == 200
