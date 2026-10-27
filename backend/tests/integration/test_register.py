"""Self-service sign-up, and signing in by email or username."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.core.rate_limit import register_limiter

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _fresh_limiter() -> Iterator[None]:
    register_limiter.reset()
    yield
    register_limiter.reset()


def _body(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "username": "Ada.Lovelace",
        "email": "ada@example.com",
        "password": PASSWORD,
        "full_name": "Ada",
    }
    body.update(over)
    return body


async def test_register_signs_you_in(api: AsyncClient) -> None:
    res = await api.post("/api/v1/auth/register", json=_body())

    assert res.status_code == 201
    assert "refresh_token" in res.headers.get("set-cookie", "")
    me = await api.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["username"] == "Ada.Lovelace"
    assert me.json()["email"] == "ada@example.com"


async def test_duplicates_are_refused_whatever_the_case(api: AsyncClient) -> None:
    assert (await api.post("/api/v1/auth/register", json=_body())).status_code == 201

    same_email = await api.post(
        "/api/v1/auth/register", json=_body(username="other", email="ADA@Example.com")
    )
    assert same_email.status_code == 409
    assert same_email.json()["detail"] == "That email already has an account."
    assert same_email.json()["errors"][0]["field"] == "email"

    same_name = await api.post(
        "/api/v1/auth/register", json=_body(username="ada.lovelace", email="new@example.com")
    )
    assert same_name.status_code == 409
    assert same_name.json()["detail"] == "That username is taken."
    assert same_name.json()["errors"][0]["field"] == "username"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("username", "ab"),
        ("username", "-leading"),
        ("username", "has space"),
        ("username", "x" * 31),
        ("password", "short"),
        ("email", "not-an-email"),
    ],
)
async def test_bad_input_is_a_validation_error(api: AsyncClient, field: str, value: str) -> None:
    res = await api.post("/api/v1/auth/register", json=_body(**{field: value}))

    assert res.status_code == 422
    assert res.json()["errors"][0]["field"] == field


async def test_sign_in_by_email_username_or_legacy_body(api: AsyncClient) -> None:
    await api.post("/api/v1/auth/register", json=_body())
    login = "/api/v1/auth/login"

    by_email = await api.post(login, json={"identifier": "ADA@example.com", "password": PASSWORD})
    by_name = await api.post(login, json={"identifier": "ada.LOVELACE", "password": PASSWORD})
    legacy = await api.post(login, json={"email": "ada@example.com", "password": PASSWORD})

    assert by_email.status_code == by_name.status_code == legacy.status_code == 200


async def test_wrong_password_looks_like_an_unknown_account(api: AsyncClient) -> None:
    await api.post("/api/v1/auth/register", json=_body())
    login = "/api/v1/auth/login"

    wrong = await api.post(login, json={"identifier": "ada.lovelace", "password": "nope-nope-nope"})
    unknown = await api.post(login, json={"identifier": "nobody", "password": "nope-nope-nope"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


async def test_login_needs_an_identifier(api: AsyncClient) -> None:
    res = await api.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert res.status_code == 422


async def test_username_available(api: AsyncClient) -> None:
    await api.post("/api/v1/auth/register", json=_body())
    url = "/api/v1/auth/username-available"

    assert (await api.get(url, params={"username": "ADA.lovelace"})).json() == {"available": False}
    assert (await api.get(url, params={"username": "someone_new"})).json() == {"available": True}
    assert (await api.get(url, params={"username": "no"})).json() == {"available": False}


async def test_register_is_rate_limited(api: AsyncClient) -> None:
    for i in range(10):
        res = await api.post(
            "/api/v1/auth/register", json=_body(username=f"user{i}", email=f"u{i}@example.com")
        )
        assert res.status_code == 201

    res = await api.post(
        "/api/v1/auth/register", json=_body(username="user99", email="u99@example.com")
    )
    assert res.status_code == 429
