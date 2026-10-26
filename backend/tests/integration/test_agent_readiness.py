"""Can an agent really do its job? The chain behind it, link by link.

An agent that updates a sheet at night depends on the app being
connected, the platform allowing that part of the app, the person having
granted the permission, their Permissions page letting the tool run, and
the platform providing what the tool needs. Each link is checked, and a
broken one says which and how to fix it.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.db.models.policy import Connection, ConnectionKind
from tests.integration.conftest import SeededPerson, seed_person

READINESS = "/api/v1/me/agents/readiness"
PLATFORM = "/api/v1/platform"

G = "https://www.googleapis.com/auth/"
BASE = ["openid", "email", G + "gmail.modify", G + "calendar.events", G + "drive.readonly"]
WITH_SHEETS = [*BASE, G + "spreadsheets"]
SHEET = "1duLbxa70UPyCCa2y33F-VpOGPWH4XLxAbt-U3Ylu1KI"

SHEET_TOOLS = ["sheets_read", "sheets_append_rows", "sheets_update_cells"]


async def _person(api: AsyncClient, session: AsyncSession) -> tuple[SeededPerson, dict[str, str]]:
    person = await seed_person(session, api, name="Asha")
    return person, {"Authorization": f"Bearer {person.token}"}


async def _connect_google(
    session: AsyncSession,
    owner_id: uuid.UUID,
    scopes: list[str] | None,
    *,
    status: str = "connected",
    enabled: bool = True,
) -> None:
    secret = {"access_token": "a", "refresh_token": "r", "expires_at": 9_999_999_999}
    session.add(
        Connection(
            owner_id=owner_id,
            kind=ConnectionKind.GOOGLE,
            label="asha@example.com",
            credential_enc=encrypt(json.dumps(secret), scope=owner_id),
            credential_last4="r",
            config={"account": "asha@example.com", **({"scopes": scopes} if scopes else {})},
            status=status,
            enabled=enabled,
        )
    )
    await session.commit()


async def _staff(api: AsyncClient, session: AsyncSession) -> dict[str, str]:
    from app.services.platform_service import PlatformService

    await PlatformService(session).create_admin(
        email="staff@platformco.com", password="platform-admin-password"
    )
    await session.commit()
    login = await api.post(
        f"{PLATFORM}/auth/login",
        json={"email": "staff@platformco.com", "password": "platform-admin-password"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _check(
    api: AsyncClient, headers: dict[str, str], tools: list[str], **extra: object
) -> dict:
    response = await api.post(READINESS, json={"tools": tools, **extra}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _failed(result: dict) -> dict[str, dict]:
    """Failed checks keyed by `layer`, then the fix code if there is one."""
    return {f"{c['layer']}:{c['fix']}": c for c in result["checks"] if not c["ok"]}


async def _allow_writes(api: AsyncClient, headers: dict[str, str]) -> None:
    for pack in ("sheets",):
        response = await api.put(
            "/api/v1/me/policies",
            json={"scope": "pack", "scope_value": pack, "side_effect": "write", "setting": "auto"},
            headers=headers,
        )
        assert response.status_code == 200, response.text


# ------------------------------------------------------------------ the app


async def test_an_app_that_is_not_connected_says_to_connect_it(
    api: AsyncClient, session: AsyncSession
) -> None:
    _, headers = await _person(api, session)
    result = await _check(api, headers, SHEET_TOOLS)

    assert result["ok"] is False
    failed = _failed(result)
    assert "app:connect:google" in failed
    assert "Google Workspace" in failed["app:connect:google"]["title"]


async def test_a_connection_without_the_permission_says_to_reconnect_and_grant_it(
    api: AsyncClient, session: AsyncSession
) -> None:
    person, headers = await _person(api, session)
    await _connect_google(session, person.owner_id, BASE)

    failed = _failed(await _check(api, headers, SHEET_TOOLS))

    assert "connection:reconnect:google:google.sheets:edit" in failed
    assert "connection:reconnect:google:google.sheets:read" in failed
    assert "app:connect:google" not in failed


async def test_a_connection_with_the_permission_passes(
    api: AsyncClient, session: AsyncSession
) -> None:
    person, headers = await _person(api, session)
    await _connect_google(session, person.owner_id, WITH_SHEETS)
    await _allow_writes(api, headers)

    result = await _check(api, headers, SHEET_TOOLS)

    assert result["ok"] is True, _failed(result)
    titles = [c["title"] for c in result["checks"]]
    assert "Google Workspace is connected" in titles
    assert "Google Sheets editing is allowed" in titles


async def test_a_connection_made_before_permissions_were_recorded_holds_the_old_set(
    api: AsyncClient, session: AsyncSession
) -> None:
    """No recorded scopes means the first version's: Gmail yes, Sheets no."""
    person, headers = await _person(api, session)
    await _connect_google(session, person.owner_id, None)

    assert (await _check(api, headers, ["gmail_search"]))["ok"] is True
    assert "connection:reconnect:google:google.sheets:read" in _failed(
        await _check(api, headers, ["sheets_read"])
    )


async def test_a_connection_that_needs_reconnecting_says_so(
    api: AsyncClient, session: AsyncSession
) -> None:
    person, headers = await _person(api, session)
    await _connect_google(session, person.owner_id, WITH_SHEETS, status="needs_reconnect")

    assert "app:reconnect:google" in _failed(await _check(api, headers, ["sheets_read"]))


async def test_a_switched_off_connection_counts_as_not_connected(
    api: AsyncClient, session: AsyncSession
) -> None:
    person, headers = await _person(api, session)
    await _connect_google(session, person.owner_id, WITH_SHEETS, enabled=False)

    assert "app:connect:google" in _failed(await _check(api, headers, ["sheets_read"]))


async def test_a_tool_that_does_not_exist_is_reported(
    api: AsyncClient, session: AsyncSession
) -> None:
    _, headers = await _person(api, session)
    failed = _failed(await _check(api, headers, ["fetch_url"]))
    assert any(c["tool"] == "fetch_url" for c in failed.values())


# ------------------------------------------------------- the platform's say


async def test_the_platform_can_close_editing_for_everyone(
    api: AsyncClient, session: AsyncSession
) -> None:
    person, headers = await _person(api, session)
    staff = await _staff(api, session)
    await _connect_google(session, person.owner_id, WITH_SHEETS)
    await _allow_writes(api, headers)

    closed = await api.put(
        f"{PLATFORM}/service-access/google.sheets/edit", json={"allowed": False}, headers=staff
    )
    assert closed.status_code == 200, closed.text

    failed = _failed(await _check(api, headers, SHEET_TOOLS))
    assert "platform:ask_admin" in failed
    assert "Google Sheets editing" in failed["platform:ask_admin"]["title"]
    # Reading is still open, and still passes.
    assert (await _check(api, headers, ["sheets_read"]))["ok"] is True


async def test_closing_reading_closes_editing_too(api: AsyncClient, session: AsyncSession) -> None:
    person, headers = await _person(api, session)
    staff = await _staff(api, session)
    await _connect_google(session, person.owner_id, WITH_SHEETS)
    await _allow_writes(api, headers)

    await api.put(
        f"{PLATFORM}/service-access/google.sheets/read", json={"allowed": False}, headers=staff
    )
    result = await _check(api, headers, ["sheets_append_rows"])
    assert result["ok"] is False


async def test_one_company_can_be_opened_while_the_platform_is_closed(
    api: AsyncClient, session: AsyncSession
) -> None:
    pilot, pilot_headers = await _person(api, session)
    other, other_headers = await _person(api, session)
    staff = await _staff(api, session)
    for owner in (pilot, other):
        await _connect_google(session, owner.owner_id, WITH_SHEETS)
    await _allow_writes(api, pilot_headers)
    await _allow_writes(api, other_headers)

    await api.put(
        f"{PLATFORM}/service-access/google.sheets/edit", json={"allowed": False}, headers=staff
    )
    opened = await api.put(
        f"{PLATFORM}/people/{pilot.owner_id}/services/google.sheets/edit",
        json={"allowed": True},
        headers=staff,
    )
    assert opened.status_code == 200, opened.text

    assert (await _check(api, pilot_headers, ["sheets_append_rows"]))["ok"] is True
    assert (await _check(api, other_headers, ["sheets_append_rows"]))["ok"] is False

    # Removing the company's ruling returns it to the platform's.
    await api.put(
        f"{PLATFORM}/people/{pilot.owner_id}/services/google.sheets/edit",
        json={"allowed": None},
        headers=staff,
    )
    assert (await _check(api, pilot_headers, ["sheets_append_rows"]))["ok"] is False


async def test_a_company_can_be_closed_for_one_service_only(
    api: AsyncClient, session: AsyncSession
) -> None:
    person, headers = await _person(api, session)
    staff = await _staff(api, session)
    await _connect_google(session, person.owner_id, [*WITH_SHEETS, G + "gmail.readonly"])

    await api.put(
        f"{PLATFORM}/people/{person.owner_id}/services/google.gmail/read",
        json={"allowed": False, "note": "Mail stays out of reach on this plan."},
        headers=staff,
    )
    failed = _failed(await _check(api, headers, ["gmail_search"]))
    assert failed["platform:ask_admin"]["detail"] == "Mail stays out of reach on this plan."
    # Another service on the same app is untouched.
    assert (await _check(api, headers, ["sheets_read"]))["ok"] is True


async def test_a_company_closed_for_the_whole_app_is_reported(
    api: AsyncClient, session: AsyncSession
) -> None:
    person, headers = await _person(api, session)
    staff = await _staff(api, session)
    await _connect_google(session, person.owner_id, WITH_SHEETS)
    await api.put(
        f"{PLATFORM}/people/{person.owner_id}/connections/google",
        json={"allowed": False, "note": "Not on your plan."},
        headers=staff,
    )
    failed = _failed(await _check(api, headers, ["sheets_read"]))
    assert failed["platform:ask_admin"]["detail"] == "Not on your plan."


async def test_a_customer_cannot_reach_the_service_rules(
    api: AsyncClient, session: AsyncSession
) -> None:
    _, headers = await _person(api, session)
    assert (await api.get(f"{PLATFORM}/service-access", headers=headers)).status_code == 401
    closed = await api.put(
        f"{PLATFORM}/service-access/google.sheets/edit", json={"allowed": False}, headers=headers
    )
    assert closed.status_code == 401


async def test_the_rules_refuse_a_made_up_service_or_level(
    api: AsyncClient, session: AsyncSession
) -> None:
    await _person(api, session)
    staff = await _staff(api, session)
    assert (
        await api.put(
            f"{PLATFORM}/service-access/google.nothing/edit", json={"allowed": False}, headers=staff
        )
    ).status_code == 422
    assert (
        await api.put(
            f"{PLATFORM}/service-access/google.sheets/root", json={"allowed": False}, headers=staff
        )
    ).status_code == 422


# ------------------------------------------------ the person's Permissions


async def test_a_blocked_tool_is_reported(api: AsyncClient, session: AsyncSession) -> None:
    person, headers = await _person(api, session)
    await _connect_google(session, person.owner_id, WITH_SHEETS)
    await api.put(
        "/api/v1/me/policies",
        json={"scope": "tool", "scope_value": "sheets_read", "setting": "blocked"},
        headers=headers,
    )
    failed = _failed(await _check(api, headers, ["sheets_read"]))
    assert "permission:permissions" in failed


async def test_asking_first_is_fine_in_chat_but_not_for_an_agent_that_runs_alone(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Writing asks first by default. At 2am nobody is there to answer."""
    person, headers = await _person(api, session)
    await _connect_google(session, person.owner_id, WITH_SHEETS)

    chat = await _check(api, headers, ["sheets_append_rows"])
    assert chat["ok"] is True

    alone = await _check(
        api,
        headers,
        ["sheets_append_rows"],
        scheduled=True,
        scope={"sheet_ids": [SHEET]},
    )
    failed = _failed(alone)
    assert "permission:permissions" in failed
    assert "asks first" in failed["permission:permissions"]["title"]

    await _allow_writes(api, headers)
    again = await _check(
        api, headers, ["sheets_append_rows"], scheduled=True, scope={"sheet_ids": [SHEET]}
    )
    assert again["ok"] is True, _failed(again)


# --------------------------------------------- what the platform must provide


async def test_web_search_needs_the_platform_to_have_a_key(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    _, headers = await _person(api, session)

    monkeypatch.setattr(get_settings(), "brave_api_key", None)
    monkeypatch.setattr(get_settings(), "tavily_api_key", None)
    assert "setup:ask_admin" in _failed(await _check(api, headers, ["web_search"]))

    monkeypatch.setattr(get_settings(), "brave_api_key", "k")
    monkeypatch.setattr(get_settings(), "tavily_api_key", None)
    assert (await _check(api, headers, ["web_search"]))["ok"] is True


# ------------------------------------------- an agent that writes on its own


async def test_a_scheduled_agent_that_writes_must_name_its_spreadsheet(
    api: AsyncClient, session: AsyncSession
) -> None:
    person, headers = await _person(api, session)
    await _connect_google(session, person.owner_id, WITH_SHEETS)
    await _allow_writes(api, headers)

    unnamed = await _check(api, headers, SHEET_TOOLS, scheduled=True)
    assert "agent:choose_sheet" in _failed(unnamed)

    garbage = await _check(
        api, headers, SHEET_TOOLS, scheduled=True, scope={"sheet_ids": ["https://evil.example/x"]}
    )
    assert "agent:choose_sheet" in _failed(garbage)

    named = await _check(
        api,
        headers,
        SHEET_TOOLS,
        scheduled=True,
        scope={"sheet_ids": [f"https://docs.google.com/spreadsheets/d/{SHEET}/edit"]},
    )
    assert named["ok"] is True, _failed(named)

    # Not needed when nobody is waiting on it to run alone.
    assert (await _check(api, headers, SHEET_TOOLS))["ok"] is True


# -------------------------------------------------- the connect screen's view


async def test_the_connect_screen_shows_what_is_allowed_and_what_is_granted(
    api: AsyncClient, session: AsyncSession
) -> None:
    person, headers = await _person(api, session)
    staff = await _staff(api, session)
    await _connect_google(session, person.owner_id, WITH_SHEETS)
    await api.put(
        f"{PLATFORM}/service-access/google.sheets/edit", json={"allowed": False}, headers=staff
    )

    rows = (await api.get("/api/v1/me/connections/services", headers=headers)).json()
    by_id = {r["id"]: r for r in rows}

    assert by_id["google.sheets"]["allowed"] == {"read": True, "edit": False}
    assert by_id["google.sheets"]["granted"] == {"read": True, "edit": True}
    assert by_id["google.gmail"]["granted"] == {"read": True, "edit": True}
    # Not connected: nothing to say about what is granted.
    assert by_id["microsoft.mail"]["granted"] is None
    # A service no tool edits is shown as read only.
    assert by_id["google.drive"]["can_edit"] is False


async def test_connecting_asks_google_only_for_what_the_person_chose(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-456")
    get_settings.cache_clear()
    try:
        _, headers = await _person(api, session)
        start = await api.post(
            "/api/v1/me/connections/oauth/google/start",
            json={"services": {"google.sheets": "edit"}},
            headers=headers,
        )
        assert start.status_code == 200, start.text
        url = start.json()["authorize_url"]
        assert "spreadsheets" in url
        assert "gmail" not in url and "drive" not in url

        nothing = await api.post(
            "/api/v1/me/connections/oauth/google/start",
            json={"services": {"google.nope": "edit"}},
            headers=headers,
        )
        assert nothing.status_code == 422
    finally:
        get_settings.cache_clear()


async def test_a_closed_service_is_not_asked_for(
    api: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-456")
    get_settings.cache_clear()
    try:
        _, headers = await _person(api, session)
        staff = await _staff(api, session)
        await api.put(
            f"{PLATFORM}/service-access/google.sheets/edit", json={"allowed": False}, headers=staff
        )
        start = await api.post(
            "/api/v1/me/connections/oauth/google/start",
            json={"services": {"google.sheets": "edit"}},
            headers=headers,
        )
        # Edit is closed, so only reading is asked for.
        assert start.status_code == 200, start.text
        url = start.json()["authorize_url"]
        assert "spreadsheets.readonly" in url
        assert "auth%2Fspreadsheets+" not in url and not url.endswith("auth%2Fspreadsheets")
    finally:
        get_settings.cache_clear()


async def test_the_platform_screen_lists_every_service_and_level(
    api: AsyncClient, session: AsyncSession
) -> None:
    person, _ = await _person(api, session)
    staff = await _staff(api, session)

    matrix = (await api.get(f"{PLATFORM}/service-access", headers=staff)).json()
    pairs = {(r["service"], r["level"]) for r in matrix}
    assert ("google.sheets", "edit") in pairs and ("google.gmail", "read") in pairs
    assert ("google.drive", "edit") not in pairs  # nothing edits Drive
    assert all(r["allowed"] for r in matrix)

    company = (await api.get(f"{PLATFORM}/people/{person.owner_id}/services", headers=staff)).json()
    assert all(r["allowed"] and not r["overridden"] for r in company)
