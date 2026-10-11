"""The invite -> accept -> login -> refresh journey, against a real database."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import seed_company


async def test_full_invite_and_login_journey(api: AsyncClient, session: AsyncSession) -> None:
    company = await seed_company(session, api, name="Acme", slug="acme")

    me = await api.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {company.member_token}"}
    )
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == company.member_email
    assert len(body["organizations"]) == 1
    assert body["organizations"][0]["role"] == "member"


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


async def test_an_invite_cannot_be_used_twice(api: AsyncClient, session: AsyncSession) -> None:
    company = await seed_company(session, api, name="Acme", slug="acme")

    invite = await api.post(
        f"/api/v1/orgs/{company.org_id}/invites",
        json={"email": "second@acme.com", "role": "member"},
        headers={"Authorization": f"Bearer {company.admin_token}"},
    )
    raw = invite.json()["invite_token"]

    first = await api.post(
        "/api/v1/auth/accept-invite", json={"token": raw, "password": "correct-horse-battery"}
    )
    assert first.status_code == 201

    second = await api.post(
        "/api/v1/auth/accept-invite", json={"token": raw, "password": "correct-horse-battery"}
    )
    assert second.status_code == 422


async def test_short_passwords_are_rejected(api: AsyncClient, session: AsyncSession) -> None:
    company = await seed_company(session, api, name="Acme", slug="acme")

    invite = await api.post(
        f"/api/v1/orgs/{company.org_id}/invites",
        json={"email": "shorty@acme.com", "role": "member"},
        headers={"Authorization": f"Bearer {company.admin_token}"},
    )
    response = await api.post(
        "/api/v1/auth/accept-invite",
        json={"token": invite.json()["invite_token"], "password": "short"},
    )
    assert response.status_code == 422


async def test_requests_without_a_token_are_rejected(api: AsyncClient) -> None:
    assert (await api.get("/api/v1/auth/me")).status_code == 401
