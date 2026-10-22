"""The parts of a connected app, and what each part needs.

"Google" is one connection, but a person may be happy to share a sheet
and not their mail. So an app is split into services (Gmail, Drive,
Sheets, Calendar), and each service into two levels: `read` (look only)
and `edit` (change or send). Three layers then decide whether a tool
may run, and every one of them has to say yes:

1. the platform, and the company within it (`ServiceAccessService`);
2. the person's own connection, which holds only the permissions they
   granted when connecting (`granted_scopes`);
3. the agent, which lists the tools it may use.

This file is the catalogue the layers share: which service a tool
belongs to, which level it needs, and which provider permission
(OAuth scope) pays for that level.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.tools.base import SideEffect, Tool

READ = "read"
EDIT = "edit"
LEVELS = (READ, EDIT)

_G = "https://www.googleapis.com/auth/"


def _norm(scope: str) -> str:
    """Microsoft returns "Mail.Read" or a full Graph URL, in any case."""
    return scope.strip().lower().removeprefix("https://graph.microsoft.com/")


@dataclass(frozen=True, slots=True)
class Service:
    id: str  # "google.sheets"
    app: str  # the connection kind: "google"
    name: str  # "Google Sheets"
    # The provider permissions that pay for each level. A level is
    # granted when ANY of its listed scopes is held; edit scopes are
    # listed under read too, since editing includes looking.
    read_scopes: tuple[str, ...]
    edit_scopes: tuple[str, ...] = ()
    # Whether any tool uses the edit level today. A service with none is
    # shown read only, so nobody is asked for a permission nothing needs.
    has_edit: bool = True

    def scopes_for(self, level: str) -> tuple[str, ...]:
        return self.edit_scopes if level == EDIT else self.read_scopes

    def grants(self, level: str, held: set[str]) -> bool:
        """Whether a connection holding these permissions has this level."""
        have = {_norm(s) for s in held}
        wanted = self.edit_scopes if level == EDIT else (*self.read_scopes, *self.edit_scopes)
        return any(_norm(s) in have for s in wanted)


SERVICES: dict[str, Service] = {
    s.id: s
    for s in (
        Service(
            "google.gmail",
            "google",
            "Gmail",
            read_scopes=(_G + "gmail.readonly",),
            edit_scopes=(_G + "gmail.modify",),
        ),
        Service(
            "google.calendar",
            "google",
            "Google Calendar",
            read_scopes=(_G + "calendar.events.readonly",),
            edit_scopes=(_G + "calendar.events",),
        ),
        Service(
            "google.drive",
            "google",
            "Google Drive",
            read_scopes=(_G + "drive.readonly",),
            has_edit=False,
        ),
        Service(
            "google.sheets",
            "google",
            "Google Sheets",
            read_scopes=(_G + "spreadsheets.readonly",),
            edit_scopes=(_G + "spreadsheets",),
        ),
        Service(
            "microsoft.mail",
            "microsoft",
            "Outlook mail",
            read_scopes=("Mail.Read",),
            edit_scopes=("Mail.ReadWrite", "Mail.Send"),
        ),
        Service(
            "microsoft.calendar",
            "microsoft",
            "Outlook calendar",
            read_scopes=("Calendars.Read",),
            edit_scopes=("Calendars.ReadWrite",),
        ),
        Service(
            "microsoft.files",
            "microsoft",
            "OneDrive",
            read_scopes=("Files.Read.All",),
            has_edit=False,
        ),
    )
}

# Which service each tool belongs to. Kept here rather than on every
# tool class so the whole map can be read, and tested, in one place.
TOOL_SERVICE: dict[str, str] = {
    "gmail_search": "google.gmail",
    "gmail_read": "google.gmail",
    "gmail_create_draft": "google.gmail",
    "gmail_send": "google.gmail",
    "google_calendar_list": "google.calendar",
    "google_calendar_create": "google.calendar",
    "google_drive_search": "google.drive",
    "google_drive_read": "google.drive",
    "sheets_read": "google.sheets",
    "sheets_create": "google.sheets",
    "sheets_append_rows": "google.sheets",
    "sheets_update_cells": "google.sheets",
    "outlook_search": "microsoft.mail",
    "outlook_read": "microsoft.mail",
    "outlook_create_draft": "microsoft.mail",
    "outlook_send": "microsoft.mail",
    "outlook_calendar_list": "microsoft.calendar",
    "outlook_calendar_create": "microsoft.calendar",
    "onedrive_search": "microsoft.files",
    "onedrive_read": "microsoft.files",
}

# What a connection asks the provider for when the person makes no
# choice: exactly what the tools that existed before services did.
DEFAULT_GRANT: dict[str, dict[str, str]] = {
    "google": {"google.gmail": EDIT, "google.calendar": EDIT, "google.drive": READ},
    "microsoft": {
        "microsoft.mail": EDIT,
        "microsoft.calendar": EDIT,
        "microsoft.files": READ,
    },
}


def level_of(tool: type[Tool]) -> str:
    """Looking is `read`; anything that changes or sends is `edit`."""
    return READ if tool.side_effect is SideEffect.READ else EDIT


def service_of(tool_name: str) -> Service | None:
    sid = TOOL_SERVICE.get(tool_name)
    return SERVICES.get(sid) if sid else None


def scopes_for_grant(app: str, grant: dict[str, str]) -> list[str]:
    """The provider permissions to ask for, given {service: level}.
    Unknown services and levels are ignored rather than trusted."""
    scopes: list[str] = []
    for sid, level in grant.items():
        service = SERVICES.get(sid)
        if service is None or service.app != app or level not in LEVELS:
            continue
        # Edit is asked for as its own scopes; read-only people get the
        # narrow read scopes, so Google shows the smaller consent.
        scopes += service.scopes_for(EDIT if level == EDIT and service.has_edit else READ)
    return list(dict.fromkeys(scopes))
