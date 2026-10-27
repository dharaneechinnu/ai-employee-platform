"""Can this agent really do its job? Asked before it is saved, and again
before every unattended run.

An agent that updates a sheet at night is only as good as the chain
behind it, and a broken link found at 2am helps nobody. So for the
tools an agent needs, this walks the chain and reports every link:

- is the app connected, switched on and working?
- has the platform (or its ruling for this person) allowed the part of the
  app it needs, for reading and for editing?
- did the person grant that permission when they connected?
- does the person's Permissions page let the tool run?
- is anything the platform must provide (web search) set up?
- for a scheduled agent that writes, which spreadsheet may it write to?

Every failed check carries a `fix`, a short code the screen turns into
a button ("Connect Google", "Reconnect"), and a plain sentence saying
what is wrong. Nothing here changes any state.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.services import DEFAULT_GRANT, EDIT, SERVICES, level_of, scopes_for_grant, service_of
from app.agent.tools.base import SideEffect, Tool
from app.agent.tools.packs.search import search_configured
from app.agent.tools.packs.sheets import sheet_ids_in, spreadsheet_id
from app.db.models.policy import Connection, ConnectionKind, PolicySetting
from app.db.models.provider import OrgConnectionAccess
from app.services.connection_service import CATALOGUE, STATUS_RECONNECT
from app.services.policy_service import PolicyService
from app.services.service_access_service import ServiceAccessService

# Applications whose tools read a Google/Microsoft-style scope list.
_SCOPED_APPS = {"google", "microsoft"}


@dataclass(slots=True)
class Check:
    ok: bool
    layer: str  # app | platform | connection | permission | agent | setup
    title: str
    detail: str
    # What the screen offers to put it right: "connect:google",
    # "reconnect:google", "permissions", "ask_admin", or None.
    fix: str | None = None
    service: str | None = None
    level: str | None = None
    tool: str | None = None


@dataclass(slots=True)
class Readiness:
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def problems(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def sentence(self) -> str:
        """The failures in one line, for a notification."""
        return " ".join(f"{c.title}: {c.detail}" for c in self.problems)

    def as_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "checks": [asdict(c) for c in self.checks]}


def _app_name(app: str) -> str:
    try:
        return str(CATALOGUE[ConnectionKind(app)]["display_name"])
    except (KeyError, ValueError):
        return app


class ReadinessService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    async def check(
        self,
        tool_names: list[str],
        *,
        scheduled: bool = False,
        scope: dict[str, object] | None = None,
    ) -> Readiness:
        resolver = await PolicyService(self.session, self.owner_id).resolver()
        access = await ServiceAccessService(self.session, self.owner_id).snapshot()
        closed_for_you = {
            r.kind.value: r
            for r in (
                await self.session.scalars(
                    select(OrgConnectionAccess).where(OrgConnectionAccess.owner_id == self.owner_id)
                )
            ).all()
            if not r.allowed
        }
        connections = await self._connections()

        checks: list[Check] = []
        tools: list[type[Tool]] = []
        for name in dict.fromkeys(tool_names):
            tool = resolver.tool(name)
            if tool is None:
                checks.append(
                    Check(
                        False,
                        "agent",
                        f"{name} is not available",
                        "That tool does not exist (it may have been removed).",
                        tool=name,
                    )
                )
            else:
                tools.append(tool)

        # --- one block per app -------------------------------------------
        apps = list(dict.fromkeys(t.requires_connection for t in tools if t.requires_connection))
        for app in apps:
            checks += self._app_checks(
                app,
                [t for t in tools if t.requires_connection == app],
                connections.get(app),
                closed_for_you.get(app),
                access,
            )

        # --- the person's Permissions page ----------------------------------
        for tool in tools:
            decision = resolver.evaluate(tool.name)
            if decision.setting is PolicySetting.BLOCKED:
                checks.append(
                    Check(
                        False,
                        "permission",
                        f"{tool.name} is blocked",
                        f"Your Permissions page does not let it run ({decision.reason}).",
                        fix="permissions",
                        tool=tool.name,
                    )
                )
            elif decision.setting is PolicySetting.ASK and scheduled:
                checks.append(
                    Check(
                        False,
                        "permission",
                        f"{tool.name} asks first",
                        "It is set to ask you every time, and nobody is there to answer when "
                        "the agent runs on its own. Set it to run automatically for this to work.",
                        fix="permissions",
                        tool=tool.name,
                    )
                )
        if tools and not any(c.layer == "permission" for c in checks):
            checks.append(
                Check(
                    True, "permission", "Your Permissions allow these tools", "Nothing blocks them."
                )
            )

        # --- things the platform itself must provide -----------------------
        if any(t.name == "web_search" for t in tools):
            from app.services.provider_service import ProviderService

            own = await ProviderService(self.session, self.owner_id).search_key()
            if own is not None or search_configured():
                checks.append(
                    Check(
                        True,
                        "setup",
                        "Web search is ready",
                        "Your search key is set up." if own else "The platform has it set up.",
                    )
                )
            else:
                checks.append(
                    Check(
                        False,
                        "setup",
                        "Web search is not set up",
                        "Add a Tavily or Brave search key under AI keys.",
                        fix="add_search_key",
                        tool="web_search",
                    )
                )

        # --- an unattended agent that writes needs a named target -------------
        writers = [t for t in tools if t.pack == "sheets" and t.side_effect is not SideEffect.READ]
        makes_its_own = any(t.name == "sheets_create" for t in tools)
        if writers and scheduled:
            ids = sheet_ids_in(scope)
            valid = [i for i in ids if spreadsheet_id(i)]
            if makes_its_own and not valid:
                checks.append(
                    Check(
                        True,
                        "agent",
                        "It will create its own spreadsheet",
                        "On its first run it makes one, and after that it writes only to that "
                        "spreadsheet.",
                    )
                )
            elif valid:
                checks.append(
                    Check(
                        True,
                        "agent",
                        "It may write to one spreadsheet only",
                        f"{len(valid)} spreadsheet{'s' if len(valid) != 1 else ''} named; "
                        "it cannot write anywhere else.",
                    )
                )
            else:
                checks.append(
                    Check(
                        False,
                        "agent",
                        "Choose the spreadsheet it may write to",
                        "An agent that runs on its own must be told which spreadsheet it may "
                        "change. Paste the sheet's address.",
                        fix="choose_sheet",
                    )
                )
        return Readiness(checks)

    # --- helpers ----------------------------------------------------------------

    async def _connections(self) -> dict[str, Connection]:
        """The connection a run would use for each app: the most recent
        one that is switched on."""
        rows = await self.session.scalars(
            select(Connection)
            .where(Connection.owner_id == self.owner_id)
            .order_by(Connection.updated_at.desc())
        )
        found: dict[str, Connection] = {}
        for conn in rows.all():
            if conn.kind.value not in found and conn.enabled:
                found[conn.kind.value] = conn
        return found

    def _app_checks(
        self,
        app: str,
        tools: list[type[Tool]],
        conn: Connection | None,
        closed: OrgConnectionAccess | None,
        access: object,
    ) -> list[Check]:
        name = _app_name(app)
        checks: list[Check] = []
        is_account = app in {k.value for k in ConnectionKind}

        if closed is not None:
            checks.append(
                Check(
                    False,
                    "platform",
                    f"{name} is switched off for you",
                    closed.note or "Whoever runs this platform has closed it for your account.",
                    fix="ask_admin",
                )
            )
        if is_account:
            if conn is None:
                checks.append(
                    Check(
                        False,
                        "app",
                        f"{name} is not connected",
                        f"Connect {name} so the agent can reach it.",
                        fix=f"connect:{app}",
                    )
                )
            elif conn.status == STATUS_RECONNECT or conn.status == "failed":
                checks.append(
                    Check(
                        False,
                        "app",
                        f"{name} needs to be reconnected",
                        conn.last_error or "Its last check failed. Reconnect it to carry on.",
                        fix=f"reconnect:{app}",
                    )
                )
            else:
                who = (conn.config or {}).get("account") or conn.label
                checks.append(Check(True, "app", f"{name} is connected", f"Connected as {who}."))

        # --- the parts of the app, one level each --------------------------------
        needed: dict[tuple[str, str], list[str]] = {}
        for tool in tools:
            service = service_of(tool.name)
            if service is not None:
                needed.setdefault((service.id, level_of(tool)), []).append(tool.name)
        held = self._held_scopes(app, conn)
        for sid, level in needed:
            service = SERVICES[sid]
            what = f"{service.name} {'editing' if level == EDIT else 'reading'}"
            decision = access.decide(sid, level)  # type: ignore[attr-defined]
            if not decision.allowed:
                who = "your account's setup" if decision.source == "person" else "the platform"
                checks.append(
                    Check(
                        False,
                        "platform",
                        f"{what} is not allowed",
                        decision.note or f"Turned off by {who}. Ask whoever runs it.",
                        fix="ask_admin",
                        service=sid,
                        level=level,
                    )
                )
                continue
            if conn is not None and held is not None and not service.grants(level, held):
                checks.append(
                    Check(
                        False,
                        "connection",
                        f"{what} was not granted",
                        f"You connected {name} without this permission. Reconnect and allow "
                        f"{service.name} {'editing' if level == EDIT else 'access'}.",
                        fix=f"reconnect:{app}:{sid}:{level}",
                        service=sid,
                        level=level,
                    )
                )
                continue
            if conn is not None:
                checks.append(
                    Check(
                        True,
                        "connection",
                        f"{what} is allowed",
                        "Allowed by the platform and granted on your connection.",
                        service=sid,
                        level=level,
                    )
                )
        return checks

    @staticmethod
    def _held_scopes(app: str, conn: Connection | None) -> set[str] | None:
        """The permissions the connection holds, or None when this kind
        of app has no scope list to check."""
        if conn is None or app not in _SCOPED_APPS:
            return None
        recorded = (conn.config or {}).get("scopes")
        if recorded:
            return {str(s) for s in recorded}
        # Connected before permissions were recorded: it holds what the
        # first version of the connection asked for.
        return set(scopes_for_grant(app, DEFAULT_GRANT[app]))
