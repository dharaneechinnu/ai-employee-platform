"""The parts of an app: which tool belongs to which service, and which
provider permission pays for it."""

from __future__ import annotations

from app.agent.services import (
    DEFAULT_GRANT,
    EDIT,
    READ,
    SERVICES,
    TOOL_SERVICE,
    level_of,
    scopes_for_grant,
    service_of,
)
from app.agent.tools import registry
from app.services.oauth_providers import get_oauth_provider


def test_every_google_and_microsoft_tool_belongs_to_a_service() -> None:
    """A tool in neither list would skip the permission layers entirely."""
    tools = [t for t in registry.all() if t.requires_connection in {"google", "microsoft"}]
    unmapped = [t.name for t in tools if service_of(t.name) is None]
    assert not unmapped, f"Add these to TOOL_SERVICE: {unmapped}"
    stale = [name for name in TOOL_SERVICE if registry.get(name) is None]
    assert not stale, f"TOOL_SERVICE names tools that no longer exist: {stale}"


def test_a_tool_uses_the_app_its_service_belongs_to() -> None:
    for tool in registry.all():
        service = service_of(tool.name)
        if service is not None:
            assert tool.requires_connection == service.app, tool.name


def test_looking_is_read_and_anything_that_changes_or_sends_is_edit() -> None:
    sheets_read, append, update = (
        registry.get(n) for n in ("sheets_read", "sheets_append_rows", "sheets_update_cells")
    )
    assert level_of(sheets_read) == READ
    assert level_of(append) == EDIT and level_of(update) == EDIT
    assert level_of(registry.get("gmail_send")) == EDIT


def test_editing_includes_looking() -> None:
    sheets = SERVICES["google.sheets"]
    editor = {"https://www.googleapis.com/auth/spreadsheets"}
    reader = {"https://www.googleapis.com/auth/spreadsheets.readonly"}
    assert sheets.grants(READ, editor) and sheets.grants(EDIT, editor)
    assert sheets.grants(READ, reader) and not sheets.grants(EDIT, reader)
    assert not sheets.grants(READ, set())


def test_microsoft_scopes_match_however_the_provider_spells_them() -> None:
    mail = SERVICES["microsoft.mail"]
    assert mail.grants(EDIT, {"https://graph.microsoft.com/Mail.ReadWrite"})
    assert mail.grants(READ, {"mail.readwrite"})
    assert not mail.grants(EDIT, {"Mail.Read"})


def test_asking_for_one_service_asks_for_that_services_permission_only() -> None:
    assert scopes_for_grant("google", {"google.sheets": EDIT}) == [
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    assert scopes_for_grant("google", {"google.sheets": READ}) == [
        "https://www.googleapis.com/auth/spreadsheets.readonly"
    ]


def test_a_service_that_cannot_be_edited_is_only_ever_read() -> None:
    drive = scopes_for_grant("google", {"google.drive": EDIT})
    assert drive == ["https://www.googleapis.com/auth/drive.readonly"]


def test_unknown_services_levels_and_other_apps_are_ignored() -> None:
    assert scopes_for_grant("google", {"google.nope": EDIT}) == []
    assert scopes_for_grant("google", {"google.sheets": "root"}) == []
    assert scopes_for_grant("google", {"microsoft.mail": EDIT}) == []


def test_connecting_with_no_choice_asks_for_exactly_what_it_always_did() -> None:
    google = get_oauth_provider("google")
    assert google is not None
    assert set(google.scopes) == {
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/drive.readonly",
    }
    microsoft = get_oauth_provider("microsoft")
    assert microsoft is not None
    assert {"Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.Read.All"} <= set(
        microsoft.scopes
    )


def test_sheets_is_opt_in() -> None:
    default = set(scopes_for_grant("google", DEFAULT_GRANT["google"]))
    assert not any("spreadsheets" in s for s in default)
    chosen = get_oauth_provider("google", {"google.sheets": EDIT})
    assert chosen is not None
    assert "https://www.googleapis.com/auth/spreadsheets" in chosen.scopes
    assert not any("gmail" in s for s in chosen.scopes)
