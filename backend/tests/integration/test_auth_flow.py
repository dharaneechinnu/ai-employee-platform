"""The invite -> accept -> login -> refresh journey, against a real database."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_company


async def test_there_is_no_public_registration_endpoint(api: AsyncClient) -> None:
    """Accounts exist only via an invite. A sign-up route would be an
    entire class of abuse we have chosen not to have."""
    response = await api.post(
        "/api/v1/auth/register", json={"email": "x@y.com", "password": "a" * 12}
    )
    assert response.status_code == 404


async def test_login_with_wrong_password_is_rejected(
    api: AsyncClient, session: AsyncSession
) -> None:
    company = await seed_company(session, api, name="Acme", slug="acme")

    response = await api.post(
        "/api/v1/auth/login", json={"email": company.admin_email, "password": "wrong-password-xx"}
    )
    assert response.status_code == 401


async def test_unknown_email_gives_the_same_message_as_a_wrong_password(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Different messages would let someone enumerate which email
    addresses have accounts."""
    company = await seed_company(session, api, name="Acme", slug="acme")

    wrong_password = await api.post(
        "/api/v1/auth/login", json={"email": company.admin_email, "password": "wrong-password-xx"}
    )
    unknown_user = await api.post(
        "/api/v1/auth/login", json={"email": "nobody@nowhere.com", "password": "wrong-password-xx"}
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"]


async def test_requests_without_a_token_are_rejected(api: AsyncClient) -> None:
    assert (await api.get("/api/v1/auth/me")).status_code == 401


async def _account_with_setup_link(session: AsyncSession, email: str) -> str:
    """Create an account the way a Platform Admin does, and return the
    raw setup link token."""
    import secrets
    from datetime import UTC, datetime, timedelta

    from app.core.security import hash_password, hash_token
    from app.db.models.identity import SetupToken, User

    user = User(email=email, password_hash=hash_password(secrets.token_urlsafe(32)))
    session.add(user)
    await session.flush()

    raw = secrets.token_urlsafe(32)
    session.add(
        SetupToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(hours=48),
        )
    )
    await session.commit()
    return raw


async def test_setting_a_password_from_the_link_signs_you_in(
    api: AsyncClient, session: AsyncSession
) -> None:
    """The only path to a usable password.

    The Platform Admin never sets one, so staff cannot sign in as a
    customer even in principle.
    """
    raw = await _account_with_setup_link(session, "newcomer@example.com")

    created = await api.post(
        "/api/v1/auth/setup",
        json={"token": raw, "password": "correct-horse-battery", "full_name": "A Newcomer"},
    )
    assert created.status_code == 201
    token = created.json()["access_token"]

    me = await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "newcomer@example.com"
    assert me.json()["full_name"] == "A Newcomer"

    again = await api.post(
        "/api/v1/auth/login",
        json={"email": "newcomer@example.com", "password": "correct-horse-battery"},
    )
    assert again.status_code == 200


async def test_a_setup_link_cannot_be_used_twice(api: AsyncClient, session: AsyncSession) -> None:
    raw = await _account_with_setup_link(session, "once@example.com")

    first = await api.post(
        "/api/v1/auth/setup", json={"token": raw, "password": "correct-horse-battery"}
    )
    assert first.status_code == 201

    # Otherwise a forwarded or leaked link would keep working, and
    # whoever used it second would own the account.
    second = await api.post(
        "/api/v1/auth/setup", json={"token": raw, "password": "a-different-password"}
    )
    assert second.status_code == 422


async def test_short_passwords_are_rejected(api: AsyncClient, session: AsyncSession) -> None:
    raw = await _account_with_setup_link(session, "short@example.com")

    response = await api.post("/api/v1/auth/setup", json={"token": raw, "password": "short"})
    assert response.status_code == 422
