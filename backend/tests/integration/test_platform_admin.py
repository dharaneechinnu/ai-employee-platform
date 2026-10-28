"""Platform Admin: the normal path.

Create an admin, sign in, create an account, hand its setup link to the
person, and suspend or restore them.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_admin(session: AsyncSession) -> tuple[str, str]:
    """Returns (email, password)."""
    from app.services.platform_service import PlatformService

    email, password = "root@platform.com", "platform-admin-password"
    await PlatformService(session).create_admin(email=email, password=password)
    await session.commit()
    return email, password


async def _sign_in(api: AsyncClient, email: str, password: str) -> str:
    response = await api.post(
        "/api/v1/platform/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def test_platform_admin_can_sign_in(api: AsyncClient, session: AsyncSession) -> None:
    email, password = await _make_admin(session)
    assert await _sign_in(api, email, password)


async def test_a_wrong_password_is_refused(api: AsyncClient, session: AsyncSession) -> None:
    """The only thing guarding this account now that 2FA is gone.

    Worth a test of its own precisely because it is the whole gate: a
    Platform Admin can create and suspend every person, and there is
    no second factor behind this check any more.
    """
    email, _ = await _make_admin(session)

    response = await api.post(
        "/api/v1/platform/auth/login",
        json={"email": email, "password": "not-the-password"},
    )
    assert response.status_code == 401


async def test_create_an_account_and_let_its_owner_set_a_password(
    api: AsyncClient, session: AsyncSession
) -> None:
    email, password = await _make_admin(session)
    token = await _sign_in(api, email, password)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        "/api/v1/platform/people",
        json={"email": "owner@victopia.com"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()

    # The setup link is returned once. The owner sets their own
    # password through it, so the Platform Admin never knows one.
    accepted = await api.post(
        "/api/v1/auth/setup",
        json={"token": body["setup_token"], "password": "owner-password-123"},
    )
    assert accepted.status_code == 201

    me = await api.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {accepted.json()['access_token']}"},
    )
    assert me.json()["email"] == "owner@victopia.com"


async def test_list_people_shows_who_and_whether_active(
    api: AsyncClient, session: AsyncSession
) -> None:
    email, password = await _make_admin(session)
    token = await _sign_in(api, email, password)
    headers = {"Authorization": f"Bearer {token}"}

    await api.post(
        "/api/v1/platform/people",
        json={"email": "owner@acme.com"},
        headers=headers,
    )

    listed = await api.get("/api/v1/platform/people", headers=headers)
    assert listed.status_code == 200
    row = next(r for r in listed.json() if r["email"] == "owner@acme.com")
    assert row["active"] is True
    assert "created_at" in row


async def test_suspend_and_restore_an_account(api: AsyncClient, session: AsyncSession) -> None:
    email, password = await _make_admin(session)
    token = await _sign_in(api, email, password)
    headers = {"Authorization": f"Bearer {token}"}

    created = await api.post(
        "/api/v1/platform/people",
        json={"email": "owner@acme.com"},
        headers=headers,
    )
    owner_id = created.json()["id"]

    suspended = await api.post(f"/api/v1/platform/people/{owner_id}/suspend", headers=headers)
    assert suspended.json()["active"] is False

    restored = await api.post(f"/api/v1/platform/people/{owner_id}/restore", headers=headers)
    assert restored.json()["active"] is True


async def test_a_customer_token_cannot_reach_platform_routes(
    api: AsyncClient, session: AsyncSession
) -> None:
    """The one security test worth keeping here. A customer token
    carries typ=access, not typ=platform_access, so it is refused even
    though its holder is an admin of their own person."""
    from tests.integration.conftest import seed_person

    person = await seed_person(session, api, name="Acme")

    response = await api.get(
        "/api/v1/platform/people",
        headers={"Authorization": f"Bearer {person.token}"},
    )
    assert response.status_code == 401


async def test_an_older_account_with_a_reserved_email_still_lists_and_signs_in(
    api: AsyncClient, session: AsyncSession
) -> None:
    """An address the validator now rejects (a reserved ending such as .test)
    must not turn the People list, or signing in, into a 500."""
    from app.core.security import hash_password
    from app.db.models.identity import User

    session.add(
        User(
            email="old-demo@example.test",
            username="old-demo",
            full_name="Old Demo",
            password_hash=hash_password("correct-horse-battery"),
        )
    )
    await session.commit()

    email, password = await _make_admin(session)
    token = await _sign_in(api, email, password)
    people = await api.get("/api/v1/platform/people", headers={"Authorization": f"Bearer {token}"})
    assert people.status_code == 200, people.text
    assert "old-demo@example.test" in [p["email"] for p in people.json()]


async def test_the_staff_console_stays_signed_in_through_a_page_refresh(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Signing in sets a session cookie, so a refresh (which loses the in-memory
    token) can resume, but only when the console header comes with it."""
    email, password = await _make_admin(session)
    signed_in = await api.post(
        "/api/v1/platform/auth/login", json={"email": email, "password": password}
    )
    assert signed_in.status_code == 200
    set_cookie = signed_in.headers["set-cookie"].lower()
    assert "platform_session=" in set_cookie and "httponly" in set_cookie
    assert "samesite=strict" in set_cookie and "max-age" not in set_cookie

    # A new "page load": no Authorization header, only the cookie (sent by hand,
    # because the test client is plain http and the cookie is Secure outside dev).
    jar = {"Cookie": f"platform_session={signed_in.json()['access_token']}"}
    resumed = await api.get("/api/v1/platform/me", headers={**jar, "X-Staff-Console": "1"})
    assert resumed.status_code == 200 and resumed.json()["email"] == email

    # The cookie alone, with no console header, is refused: a cross-site page cannot add it.
    assert (await api.get("/api/v1/platform/me", headers=jar)).status_code == 401

    # Signing out asks the browser to delete the cookie.
    out = await api.post("/api/v1/platform/auth/logout", headers={"X-Staff-Console": "1"})
    assert out.status_code == 204 and "platform_session=" in out.headers["set-cookie"].lower()
