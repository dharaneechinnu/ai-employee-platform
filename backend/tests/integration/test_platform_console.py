"""The staff console's facts and counts: how people joined, when they were
last around, what they have built, and the switches staff can flip.

Every field here is a count, a date or a yes or no. The sweep in
test_platform_cannot_read_customer_data.py checks that none of these
endpoints carries customer content; these check that the numbers are
right and that every new staff action is written to the audit log.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import register_limiter
from tests.integration.conftest import seed_person

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _fresh_limiter() -> Iterator[None]:
    register_limiter.reset()
    yield
    register_limiter.reset()


@pytest.fixture
async def staff(api: AsyncClient, session: AsyncSession) -> dict[str, str]:
    from app.services.platform_service import PlatformService

    email, password = "ops@platformco.com", "platform-admin-password"
    await PlatformService(session).create_admin(email=email, password=password)
    await session.commit()
    response = await api.post(
        "/api/v1/platform/auth/login", json={"email": email, "password": password}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _sign_up(api: AsyncClient, username: str, email: str) -> str:
    res = await api.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": PASSWORD, "full_name": username},
    )
    assert res.status_code == 201, res.text
    return str(res.json()["access_token"])


async def _person(api: AsyncClient, staff: dict[str, str], email: str) -> dict:
    listed = await api.get("/api/v1/platform/people", headers=staff)
    return next(p for p in listed.json() if p["email"] == email)


async def test_me_says_who_is_signed_in(api: AsyncClient, staff: dict[str, str]) -> None:
    me = await api.get("/api/v1/platform/me", headers=staff)
    assert me.status_code == 200
    assert me.json()["email"] == "ops@platformco.com"


async def test_people_say_how_they_joined_and_when_last_active(
    api: AsyncClient, staff: dict[str, str]
) -> None:
    await _sign_up(api, "asha_r", "asha@example.com")
    invited = await api.post(
        "/api/v1/platform/people",
        json={"email": "ravi@example.com", "full_name": "Ravi Kumar"},
        headers=staff,
    )
    assert invited.status_code == 201

    asha = await _person(api, staff, "asha@example.com")
    assert asha["username"] == "asha_r"
    assert asha["joined_via"] == "self"
    assert asha["setup_link"] is None
    # Signing up signs you in, so they have been active.
    assert asha["last_active_at"] is not None

    ravi = await _person(api, staff, "ravi@example.com")
    assert ravi["joined_via"] == "invited"
    assert ravi["setup_link"] == "waiting"
    assert ravi["setup_link_expires_at"] is not None
    assert ravi["last_active_at"] is None

    # Using the link moves it to "used" and counts as being active.
    await api.post(
        "/api/v1/auth/setup",
        json={"token": invited.json()["setup_token"], "password": "ravi-password-123"},
    )
    ravi = await _person(api, staff, "ravi@example.com")
    assert ravi["setup_link"] == "used"
    assert ravi["setup_link_expires_at"] is None
    assert ravi["last_active_at"] is not None


async def test_overview_counts(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    token = await _sign_up(api, "asha_r", "asha@example.com")
    await _sign_up(api, "meera", "meera@example.com")
    await api.post("/api/v1/platform/people", json={"email": "ravi@example.com"}, headers=staff)

    headers = {"Authorization": f"Bearer {token}"}
    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "gemini", "api_key": "AIza-test-key-0001"},
        headers=headers,
    )
    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "anthropic", "api_key": "sk-ant-test-0002", "plan": "paid"},
        headers=headers,
    )

    meera = await _person(api, staff, "meera@example.com")
    await api.post(f"/api/v1/platform/people/{meera['id']}/suspend", headers=staff)

    body = (await api.get("/api/v1/platform/overview", headers=staff)).json()
    assert body["people_total"] == 3
    assert body["people_active"] == 2
    assert body["people_suspended"] == 1
    assert body["joined_this_week_self"] == 2
    assert body["joined_this_week_invited"] == 1
    assert body["setup_links_waiting"] == 1
    assert body["ai_keys_total"] == 2
    # Gemini has a free tier and no plan was given; Anthropic was said to be paid.
    assert body["ai_keys_free"] == 1
    assert body["ai_keys_paid"] == 1
    assert body["agents_built"] == 0
    assert body["runs_this_week"] == 0


async def test_person_detail_has_counts_and_yes_or_no(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    asha = await seed_person(session, api, email="asha@example.com", name="Asha")
    headers = {"Authorization": f"Bearer {asha.token}"}
    await api.post(
        "/api/v1/me/connections",
        json={
            "kind": "slack",
            "label": "Team",
            "secret": "https://hooks.slack.com/services/T000/B000/SECRETPART",
            "config": {"channel": "#team"},
        },
        headers=headers,
    )

    body = (await api.get(f"/api/v1/platform/people/{asha.owner_id}", headers=staff)).json()
    assert body["agent_count"] == 0
    assert body["runs_this_week"] == 0
    assert body["joined_via"] == "self"
    apps = {a["kind"]: a["connected"] for a in body["apps"]}
    assert apps["slack"] is True
    assert apps["github"] is False
    # Yes or no only: the webhook, which is the secret, is nowhere.
    assert "SECRETPART" not in str(body)


async def test_suspend_reason_goes_into_the_audit_entry(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    asha = await seed_person(session, api, email="asha@example.com", name="Asha Raman")

    res = await api.post(
        f"/api/v1/platform/people/{asha.owner_id}/suspend",
        json={"reason": "Asked to close her account"},
        headers=staff,
    )
    assert res.status_code == 200
    assert res.json()["active"] is False

    entries = (
        await api.get(
            "/api/v1/platform/audit", params={"target_id": str(asha.owner_id)}, headers=staff
        )
    ).json()
    assert [e["action"] for e in entries] == ["account_suspended"]
    assert entries[0]["detail"] == "Asked to close her account"
    # The log names the person, not just their id.
    assert entries[0]["target_label"] == "Asha Raman"


async def test_suspend_without_a_reason_still_works(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    asha = await seed_person(session, api, email="asha@example.com")
    res = await api.post(f"/api/v1/platform/people/{asha.owner_id}/suspend", headers=staff)
    assert res.status_code == 200
    entries = (await api.get("/api/v1/platform/audit", headers=staff)).json()
    suspended = next(e for e in entries if e["action"] == "account_suspended")
    assert suspended["detail"] is None


async def test_a_new_setup_link_ends_the_old_one(api: AsyncClient, staff: dict[str, str]) -> None:
    created = await api.post(
        "/api/v1/platform/people", json={"email": "ravi@example.com"}, headers=staff
    )
    old = created.json()["setup_token"]

    fresh = await api.post(
        f"/api/v1/platform/people/{created.json()['id']}/setup-link", headers=staff
    )
    assert fresh.status_code == 201
    new = fresh.json()["setup_token"]
    assert new != old

    refused = await api.post(
        "/api/v1/auth/setup", json={"token": old, "password": "ravi-password-123"}
    )
    assert refused.status_code == 422
    accepted = await api.post(
        "/api/v1/auth/setup", json={"token": new, "password": "ravi-password-123"}
    )
    assert accepted.status_code == 201

    actions = [e["action"] for e in (await api.get("/api/v1/platform/audit", headers=staff)).json()]
    assert "setup_link_reissued" in actions


async def test_no_setup_link_for_an_account_with_a_password(
    api: AsyncClient, staff: dict[str, str]
) -> None:
    """A setup link sets the password, so one for a live account would let
    staff sign in as that person. It is refused."""
    await _sign_up(api, "asha_r", "asha@example.com")
    asha = await _person(api, staff, "asha@example.com")
    res = await api.post(f"/api/v1/platform/people/{asha['id']}/setup-link", headers=staff)
    assert res.status_code == 409

    created = await api.post(
        "/api/v1/platform/people", json={"email": "ravi@example.com"}, headers=staff
    )
    await api.post(
        "/api/v1/auth/setup",
        json={"token": created.json()["setup_token"], "password": "ravi-password-123"},
    )
    used = await api.post(
        f"/api/v1/platform/people/{created.json()['id']}/setup-link", headers=staff
    )
    assert used.status_code == 409


async def test_closing_an_app_for_everyone(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    asha = await seed_person(session, api, email="asha@example.com")
    pilot = await seed_person(session, api, email="pilot@example.com")
    asha_h = {"Authorization": f"Bearer {asha.token}"}
    pilot_h = {"Authorization": f"Bearer {pilot.token}"}

    rows = (await api.get("/api/v1/platform/app-access", headers=staff)).json()
    assert {r["kind"] for r in rows} >= {"email", "github", "database", "slack", "teams"}
    assert all(r["allowed"] for r in rows)

    closed = await api.put(
        "/api/v1/platform/app-access/database", json={"allowed": False}, headers=staff
    )
    assert closed.status_code == 200
    assert next(r for r in closed.json() if r["kind"] == "database")["allowed"] is False

    # One person may still be let in, which beats the everyone-level rule.
    await api.put(
        f"/api/v1/platform/people/{pilot.owner_id}/connections/database",
        json={"allowed": True},
        headers=staff,
    )

    listing = (await api.get("/api/v1/me/connections/available", headers=asha_h)).json()
    database = next(a for a in listing if a["kind"] == "database")
    assert database["allowed"] is False
    assert "everyone" in database["blocked_note"]

    listing = (await api.get("/api/v1/me/connections/available", headers=pilot_h)).json()
    assert next(a for a in listing if a["kind"] == "database")["allowed"] is True

    # The per-person view says what everyone gets.
    person = (
        await api.get(f"/api/v1/platform/people/{asha.owner_id}/connections", headers=staff)
    ).json()
    row = next(r for r in person if r["kind"] == "database")
    assert row["allowed"] is False
    assert row["everyone_allowed"] is False
    assert row["overridden"] is False

    apps = (await api.get("/api/v1/platform/app-access", headers=staff)).json()
    assert next(r for r in apps if r["kind"] == "database")["people_with_own_settings"] == 1

    actions = [e["action"] for e in (await api.get("/api/v1/platform/audit", headers=staff)).json()]
    assert "app_blocked" in actions


async def test_an_unknown_app_kind_is_refused(api: AsyncClient, staff: dict[str, str]) -> None:
    res = await api.put("/api/v1/platform/app-access/fax", json={"allowed": False}, headers=staff)
    assert res.status_code == 404


async def test_providers_say_how_many_people_use_them(
    api: AsyncClient, session: AsyncSession, staff: dict[str, str]
) -> None:
    asha = await seed_person(session, api, email="asha@example.com")
    await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "groq", "api_key": "gsk-test-key-0003"},
        headers={"Authorization": f"Bearer {asha.token}"},
    )
    await api.patch("/api/v1/platform/providers/mistral", json={"enabled": False}, headers=staff)

    rows = {
        p["key"]: p for p in (await api.get("/api/v1/platform/providers", headers=staff)).json()
    }
    assert rows["groq"]["people_connected"] == 1
    assert rows["groq"]["free_tier"] is True
    assert rows["custom"]["is_local"] is True
    assert rows["mistral"]["paused_by_email"] == "ops@platformco.com"
    assert rows["mistral"]["paused_at"] is not None
    assert rows["groq"]["paused_at"] is None
    assert "gsk-test-key-0003" not in str(rows)
