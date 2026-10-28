"""Connections: the outside apps a person lets their agents use.

Two ways in:

- **One click (OAuth)** for Google and Microsoft. The person signs in
  with their provider, approves the listed permissions, and we keep the
  refresh token. Nobody pastes a password.
- **Manual** for a mailbox over IMAP/SMTP or a PostgreSQL database,
  where the secret is an app password or a read-only database password.

Either way the secret is handled like a provider key: encrypted with
the person's own key, never returned by any endpoint, and never placed
in the model's context. `resolve_grants` is the single read path, and
only the worker calls it, at the start of a run.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import Grant
from app.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.core.observability import get_logger
from app.core.signed import InvalidSignedTokenError, sign_for, verify
from app.db.models.policy import Connection, ConnectionKind
from app.db.models.provider import OrgConnectionAccess, OrgOAuthApp, PlatformConnectionAccess
from app.services.oauth_providers import OAuthProvider, get_oauth_provider, resolve_client

log = get_logger(__name__)

# Refresh an access token this long before it expires. A run lasts at
# most fifteen minutes (the worker's job timeout), so a token resolved
# at the start must outlive the run.
REFRESH_MARGIN_S = 20 * 60
STATE_MINUTES = 10
HTTP_TIMEOUT_S = 15.0

STATUS_CONNECTED = "connected"
STATUS_UNTESTED = "untested"
STATUS_FAILED = "failed"
STATUS_RECONNECT = "needs_reconnect"


def _client() -> httpx.AsyncClient:
    """One place to build the HTTP client, so tests can swap in a fake."""
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)


# ------------------------------------------------------------------ catalogue


class EmailConfig(BaseModel):
    username: str = Field(min_length=3, max_length=320)
    imap_host: str = Field(default="imap.gmail.com", max_length=255)
    smtp_host: str = Field(default="smtp.gmail.com", max_length=255)
    smtp_port: int = Field(default=465, ge=1, le=65535)
    drafts_folder: str = Field(default="[Gmail]/Drafts", max_length=100)


class DatabaseConfig(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=100)


class ChannelConfig(BaseModel):
    """Only a name, so the person can tell their channels apart: the
    webhook itself decides where messages go."""

    channel: str = Field(default="", max_length=100)


class GithubConfig(BaseModel):
    """Nothing to fill in: the token says who you are and which
    repositories it may reach."""


MANUAL_CONFIGS: dict[ConnectionKind, type[BaseModel]] = {
    ConnectionKind.EMAIL: EmailConfig,
    ConnectionKind.DATABASE: DatabaseConfig,
    ConnectionKind.GITHUB: GithubConfig,
    ConnectionKind.SLACK: ChannelConfig,
    ConnectionKind.TEAMS: ChannelConfig,
}

# Fields are described here rather than in the frontend, so adding a
# manual kind is a backend change only.
_EMAIL_FIELDS = [
    {"key": "username", "label": "Email address", "placeholder": "ops@company.com"},
    {"key": "imap_host", "label": "IMAP server", "placeholder": "imap.gmail.com"},
    {"key": "smtp_host", "label": "SMTP server", "placeholder": "smtp.gmail.com"},
    {"key": "smtp_port", "label": "SMTP port", "placeholder": "465"},
]
_DATABASE_FIELDS = [
    {"key": "host", "label": "Host", "placeholder": "db.company.com"},
    {"key": "port", "label": "Port", "placeholder": "5432"},
    {"key": "database", "label": "Database", "placeholder": "analytics"},
    {"key": "username", "label": "Read-only user", "placeholder": "readonly"},
]

CATALOGUE: dict[ConnectionKind, dict[str, Any]] = {
    ConnectionKind.GOOGLE: {
        "display_name": "Google Workspace",
        "description": "Gmail, Google Calendar and Google Drive, with one sign-in.",
        "auth": "oauth",
        "apps": ["Gmail", "Calendar", "Drive"],
    },
    ConnectionKind.MICROSOFT: {
        "display_name": "Microsoft 365",
        "description": "Outlook mail, Outlook calendar and OneDrive, with one sign-in.",
        "auth": "oauth",
        "apps": ["Outlook", "Calendar", "OneDrive"],
    },
    ConnectionKind.EMAIL: {
        "display_name": "Any mailbox (IMAP)",
        "description": "Any provider that offers IMAP and SMTP with an app password.",
        "auth": "manual",
        "apps": ["Email"],
        "fields": _EMAIL_FIELDS,
        "secret_label": "App password",
    },
    ConnectionKind.GITHUB: {
        "display_name": "GitHub",
        "description": (
            "Read code, issues and pull requests, check CI, and propose changes as pull "
            "requests. Use a fine-grained token limited to the repositories you choose."
        ),
        "auth": "manual",
        "apps": ["Code", "Issues", "Pull requests", "Actions"],
        "fields": [],
        "secret_label": "Personal access token",
    },
    ConnectionKind.SLACK: {
        "display_name": "Slack channel",
        "description": (
            "Let agents post summaries and alerts to one Slack channel. In Slack, add an "
            "Incoming Webhook to the channel and paste its URL here."
        ),
        "auth": "manual",
        "apps": ["Slack"],
        "fields": [{"key": "channel", "label": "Channel name", "placeholder": "#team-updates"}],
        "secret_label": "Incoming webhook URL",
    },
    ConnectionKind.TEAMS: {
        "display_name": "Microsoft Teams channel",
        "description": (
            "Let agents post summaries and alerts to one Teams channel. In the channel, use "
            "Workflows > 'Post to a channel when a webhook request is received' and paste its URL."
        ),
        "auth": "manual",
        "apps": ["Teams"],
        "fields": [{"key": "channel", "label": "Channel name", "placeholder": "Team updates"}],
        "secret_label": "Workflow webhook URL",
    },
    ConnectionKind.DATABASE: {
        "display_name": "PostgreSQL",
        "description": "Read-only questions against your own database.",
        "auth": "manual",
        "apps": ["Database"],
        "fields": _DATABASE_FIELDS,
        "secret_label": "Password",
    },
}


@dataclass(slots=True)
class AvailableConnection:
    kind: str
    display_name: str
    description: str
    auth: str
    apps: list[str]
    # False for an OAuth kind the platform has not registered an app
    # for yet. The UI shows it greyed out rather than failing on click.
    configured: bool
    tools: list[str]
    fields: list[dict[str, str]] = field(default_factory=list)
    secret_label: str | None = None
    # False when a Platform Admin has closed this connection for this
    # person specifically. Separate from `configured` so the UI can
    # say which of the two it is — "nobody has set this up" and "your
    # provider turned this off for you" need different next steps.
    allowed: bool = True
    blocked_note: str | None = None


@dataclass(slots=True)
class ConnectionView:
    """What the API returns about a connection. No secret, ever."""

    id: uuid.UUID
    kind: str
    display_name: str
    label: str
    account: str | None
    status: str
    credential_last4: str
    last_tested_at: datetime | None
    last_error: str | None
    enabled: bool
    created_at: datetime
    config: dict[str, Any]


def tools_for(kind: str) -> list[str]:
    from app.agent.tools.registry import registry

    return [t.name for t in registry.all() if t.requires_connection == kind]


@dataclass(frozen=True, slots=True)
class ConnectionRuling:
    """Whether one kind of app is open to one person, and who said so.

    `source` is "person" when a Platform Admin set it for this person,
    or "platform" when it was set for everyone. No ruling at all means
    open, and is not represented here.
    """

    allowed: bool
    source: str
    note: str | None = None


async def connection_rulings(
    session: AsyncSession, owner_id: uuid.UUID
) -> dict[ConnectionKind, ConnectionRuling]:
    """The rulings that apply to this person, one per kind of app.

    A person's own ruling beats the everyone-level one, in either
    direction, the same way it does for the parts of an app. A kind with
    no ruling at either level is open and is left out of the result.
    """
    out: dict[ConnectionKind, ConnectionRuling] = {
        row.kind: ConnectionRuling(
            row.allowed,
            "platform",
            None
            if row.allowed
            else f"{CATALOGUE.get(row.kind, {}).get('display_name', row.kind.value)} "
            "is switched off for everyone on this platform for now.",
        )
        for row in (await session.scalars(select(PlatformConnectionAccess))).all()
    }
    for row in (
        await session.scalars(
            select(OrgConnectionAccess).where(OrgConnectionAccess.owner_id == owner_id)
        )
    ).all():
        out[row.kind] = ConnectionRuling(row.allowed, "person", row.note)
    return out


# ------------------------------------------------------------------ service


class ConnectionService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    # --- reading -------------------------------------------------------

    async def _access(self) -> dict[ConnectionKind, ConnectionRuling]:
        """The rulings that apply to this person, keyed by kind: their own,
        or else the everyone-level one. Absent means open."""
        return await connection_rulings(self.session, self.owner_id)

    async def available(self) -> list[AvailableConnection]:
        access = await self._access()
        out: list[AvailableConnection] = []
        for kind, meta in CATALOGUE.items():
            ruling = access.get(kind)
            oauth = get_oauth_provider(kind.value)
            configured = (
                await resolve_client(self.session, oauth, self.owner_id) is not None
                if oauth
                else True
            )
            out.append(
                AvailableConnection(
                    kind=kind.value,
                    display_name=meta["display_name"],
                    description=meta["description"],
                    auth=meta["auth"],
                    apps=meta["apps"],
                    configured=configured,
                    tools=tools_for(kind.value),
                    fields=meta.get("fields", []),
                    secret_label=meta.get("secret_label"),
                    allowed=ruling.allowed if ruling else True,
                    blocked_note=None if ruling is None or ruling.allowed else ruling.note,
                )
            )
        return out

    async def list_all(self) -> list[ConnectionView]:
        rows = await self.session.scalars(
            select(Connection)
            .where(Connection.owner_id == self.owner_id)
            .order_by(Connection.kind, Connection.created_at)
        )
        return [self._view(c) for c in rows.all()]

    async def get(self, connection_id: uuid.UUID) -> Connection:
        conn = await self.session.scalar(
            select(Connection).where(
                Connection.id == connection_id, Connection.owner_id == self.owner_id
            )
        )
        if conn is None:
            raise NotFoundError("No such connection.")
        return conn

    def view(self, conn: Connection) -> ConnectionView:
        return self._view(conn)

    @staticmethod
    def _view(conn: Connection) -> ConnectionView:
        meta = CATALOGUE.get(conn.kind, {})
        public = {k: v for k, v in (conn.config or {}).items() if not k.startswith("_")}
        return ConnectionView(
            id=conn.id,
            kind=conn.kind.value,
            display_name=meta.get("display_name", conn.kind.value),
            label=conn.label,
            account=public.get("account") or public.get("username"),
            status=conn.status,
            credential_last4=conn.credential_last4,
            last_tested_at=conn.last_tested_at,
            last_error=conn.last_error,
            enabled=conn.enabled,
            created_at=conn.created_at,
            config=public,
        )

    # --- this person's own OAuth app -----------------------------------

    async def own_oauth_apps(self) -> dict[str, dict[str, str]]:
        """What this person has registered, by provider key.

        Only the client id and the last four of the secret. There is no
        read path for the secret itself, here or anywhere.
        """
        rows = await self.session.scalars(
            select(OrgOAuthApp).where(OrgOAuthApp.owner_id == self.owner_id)
        )
        return {
            row.provider.value: {"client_id": row.client_id, "secret_last4": row.secret_last4}
            for row in rows.all()
        }

    async def save_own_oauth_app(
        self, *, kind: str, client_id: str, client_secret: str
    ) -> OrgOAuthApp:
        """Register this person's own Google or Microsoft app.

        The point is that nobody else has to act first: a person can
        switch one-click on for themselves, with their own app on the
        consent screen, without the platform operator registering
        anything.
        """
        provider = get_oauth_provider(kind)
        if provider is None:
            raise ValidationError(f"'{kind}' is not connected with one click.")

        await self._require_allowed(provider.kind)

        existing = await self.session.scalar(
            select(OrgOAuthApp).where(
                OrgOAuthApp.owner_id == self.owner_id, OrgOAuthApp.provider == provider.kind
            )
        )
        # The person's own key, so their scope opens it.
        ciphertext = encrypt(client_secret, scope=self.owner_id)
        last4 = client_secret[-4:] if len(client_secret) >= 4 else "????"

        if existing is None:
            existing = OrgOAuthApp(
                owner_id=self.owner_id,
                provider=provider.kind,
                client_id=client_id,
                client_secret_enc=ciphertext,
                secret_last4=last4,
            )
            self.session.add(existing)
        else:
            existing.client_id = client_id
            existing.client_secret_enc = ciphertext
            existing.secret_last4 = last4

        await self.session.flush()
        return existing

    async def delete_own_oauth_app(self, kind: str) -> None:
        """Fall back to the platform's app, if there is one."""
        provider = get_oauth_provider(kind)
        row = (
            await self.session.scalar(
                select(OrgOAuthApp).where(
                    OrgOAuthApp.owner_id == self.owner_id, OrgOAuthApp.provider == provider.kind
                )
            )
            if provider
            else None
        )
        if row is None:
            raise NotFoundError(f"No {kind} app is registered for you.")
        await self.session.delete(row)

    # --- one click (OAuth) --------------------------------------------

    async def _require_allowed(self, kind: ConnectionKind) -> None:
        """Refuse a connection a Platform Admin has closed for us.

        Checked on the way in as well as in the listing: a greyed-out
        button is a courtesy, not a control, and the request can be
        made without ever loading the page.
        """
        ruling = (await self._access()).get(kind)
        if ruling is not None and not ruling.allowed:
            # Forbidden, not unprocessable: the request is well formed
            # and this person simply may not do this. A client that
            # retries on 422 would retry this forever.
            raise PermissionDeniedError(
                ruling.note
                or f"{CATALOGUE[kind]['display_name']} is not available on your plan. "
                "Ask whoever runs Baton to open it for you."
            )

    async def _allowed_grant(self, kind: str, services: dict[str, str]) -> dict[str, str]:
        """What the person asked to share, cut down to what the platform
        allows for this person. Edit falls back to read when only read
        is open; a service nothing allows is dropped."""
        from app.agent.services import EDIT, LEVELS, READ, SERVICES
        from app.services.service_access_service import ServiceAccessService

        rules = await ServiceAccessService(self.session, self.owner_id).snapshot()
        grant: dict[str, str] = {}
        for sid, level in services.items():
            service = SERVICES.get(sid)
            if service is None or service.app != kind or level not in LEVELS:
                continue
            if level == EDIT and service.has_edit and rules.decide(sid, EDIT).allowed:
                grant[sid] = EDIT
            elif rules.decide(sid, READ).allowed:
                grant[sid] = READ
        if not grant:
            raise ValidationError(
                "Choose at least one thing to share, and one your platform allows."
            )
        return grant

    async def services_view(self) -> list[dict[str, Any]]:
        """Every service with what the platform allows and what the
        person's connection has been granted, for the connect screen."""
        from app.agent.services import EDIT, READ, SERVICES
        from app.services.service_access_service import ServiceAccessService

        rules = await ServiceAccessService(self.session, self.owner_id).snapshot()
        rows = await self.session.scalars(
            select(Connection)
            .where(Connection.owner_id == self.owner_id, Connection.enabled.is_(True))
            .order_by(Connection.updated_at.desc())
        )
        latest: dict[str, Connection] = {}
        for conn in rows.all():
            latest.setdefault(conn.kind.value, conn)
        out: list[dict[str, Any]] = []
        for service in SERVICES.values():
            read, edit = rules.decide(service.id, READ), rules.decide(service.id, EDIT)
            current = latest.get(service.app)
            held = None
            if current is not None:
                from app.services.readiness_service import ReadinessService

                scopes = ReadinessService._held_scopes(service.app, current)
                held = (
                    None
                    if scopes is None
                    else {
                        "read": service.grants(READ, scopes),
                        "edit": service.has_edit and service.grants(EDIT, scopes),
                    }
                )
            out.append(
                {
                    "id": service.id,
                    "app": service.app,
                    "name": service.name,
                    "can_edit": service.has_edit,
                    "allowed": {"read": read.allowed, "edit": service.has_edit and edit.allowed},
                    "note": next((d.note for d in (read, edit) if not d.allowed and d.note), None),
                    "granted": held,
                }
            )
        return out

    async def _provider(
        self, kind: str, services: dict[str, str] | None = None
    ) -> tuple[OAuthProvider, tuple[str, str]]:
        grant = await self._allowed_grant(kind, services) if services else None
        provider = get_oauth_provider(kind, grant)
        if provider is None:
            raise ValidationError(f"'{kind}' does not support one-click connection.")
        client = await resolve_client(self.session, provider, self.owner_id)
        if client is None:
            raise ValidationError(
                f"{provider.display_name} sign-in is not set up yet. Add your own "
                f"{provider.display_name} app under Connections, or ask whoever runs "
                "Baton to register one for everybody."
            )
        return provider, client

    async def start_oauth(
        self, kind: str, *, user_id: uuid.UUID, services: dict[str, str] | None = None
    ) -> str:
        """`services` is {service: level} the person chose to share, for
        example {"google.sheets": "edit"}. Only what the platform allows
        is requested: asking for a permission nothing may use would put
        a scary line on the consent screen for no reason."""
        provider, (client_id, _) = await self._provider(kind, services)
        await self._require_allowed(provider.kind)
        # The state is signed, so the callback can trust which person
        # started this without a table of pending sign-ins.
        state = sign_for(
            "oauth_state",
            {"org": str(self.owner_id), "sub": str(user_id), "kind": provider.kind.value},
            minutes=STATE_MINUTES,
        )
        return provider.authorize(client_id=client_id, state=state)

    @staticmethod
    def read_state(state: str, kind: str) -> tuple[uuid.UUID, uuid.UUID]:
        """(owner_id, user_id) from a callback's state, or raise."""
        try:
            claims = verify(state, "oauth_state")
            if claims.get("kind") != kind:
                raise InvalidSignedTokenError("This sign-in was started for another provider.")
            return uuid.UUID(claims["org"]), uuid.UUID(claims["sub"])
        except (KeyError, ValueError) as exc:
            raise InvalidSignedTokenError("This sign-in link is not valid.") from exc

    async def complete_oauth(self, kind: str, *, code: str, user_id: uuid.UUID) -> Connection:
        provider, (client_id, client_secret) = await self._provider(kind)
        # Checked again here: a sign-in started before the block, or a
        # callback replayed by hand, would otherwise land a connection
        # the person is not entitled to.
        await self._require_allowed(provider.kind)

        async with _client() as http:
            token_resp = await http.post(
                provider.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": provider.redirect_uri(),
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
            )
            if token_resp.status_code >= 400:
                log.warning("oauth_exchange_failed", kind=kind, status=token_resp.status_code)
                raise ValidationError("The sign-in could not be completed. Please try again.")
            tokens = token_resp.json()

            access_token = tokens.get("access_token")
            if not access_token:
                raise ValidationError("The provider did not return an access token.")

            me = await http.get(
                provider.userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
            )
            profile = me.json() if me.status_code < 400 else {}

        account = (
            profile.get("email")
            or profile.get("mail")
            or profile.get("userPrincipalName")
            or f"{provider.display_name} account"
        )

        existing = await self.session.scalar(
            select(Connection).where(
                Connection.owner_id == self.owner_id,
                Connection.kind == provider.kind,
                Connection.label == account,
            )
        )

        refresh_token = tokens.get("refresh_token")
        if not refresh_token and existing is not None:
            # Reconnecting the same account: some providers only issue a
            # refresh token on the first consent. Keep the one we have.
            refresh_token = json.loads(decrypt(existing.credential_enc, scope=self.owner_id)).get(
                "refresh_token"
            )
        if not refresh_token:
            raise ValidationError(
                "The provider did not grant offline access, so the connection would stop "
                "working within the hour. Please try again and accept all permissions."
            )

        secret = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": int(time.time()) + int(tokens.get("expires_in", 3600)),
        }
        config = {
            "account": account,
            "name": profile.get("name") or profile.get("displayName"),
            "scopes": (tokens.get("scope") or " ".join(provider.scopes)).split(),
            "connected_by": str(user_id),
        }

        conn = existing or Connection(
            owner_id=self.owner_id, kind=provider.kind, label=account[:100]
        )
        conn.credential_enc = encrypt(json.dumps(secret), scope=self.owner_id)
        conn.credential_last4 = refresh_token[-4:]
        conn.config = config
        conn.status = STATUS_CONNECTED
        conn.last_tested_at = datetime.now(UTC)
        conn.last_error = None
        conn.enabled = True
        if existing is None:
            self.session.add(conn)
        await self.session.flush()
        log.info("connection_oauth_connected", owner_id=str(self.owner_id), kind=kind)
        return conn

    async def _fresh_access_token(self, conn: Connection, *, force: bool = False) -> str:
        """The stored access token, refreshed first if it is close to
        expiring. A refresh that the provider rejects means the person
        revoked access, so the connection is marked for reconnecting."""
        secret = json.loads(decrypt(conn.credential_enc, scope=self.owner_id))
        if not force and secret.get("expires_at", 0) - time.time() > REFRESH_MARGIN_S:
            return str(secret["access_token"])

        provider, (client_id, client_secret) = await self._provider(conn.kind.value)
        async with _client() as http:
            resp = await http.post(
                provider.token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": secret["refresh_token"],
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
            )
        if resp.status_code >= 400:
            conn.status = STATUS_RECONNECT
            conn.last_error = "Access was revoked or has expired. Connect the account again."
            conn.last_tested_at = datetime.now(UTC)
            await self.session.flush()
            raise ValidationError(conn.last_error)

        fresh = resp.json()
        secret["access_token"] = fresh["access_token"]
        secret["expires_at"] = int(time.time()) + int(fresh.get("expires_in", 3600))
        if fresh.get("refresh_token"):
            # Microsoft rotates refresh tokens; Google usually does not.
            secret["refresh_token"] = fresh["refresh_token"]
            conn.credential_last4 = fresh["refresh_token"][-4:]
        conn.credential_enc = encrypt(json.dumps(secret), scope=self.owner_id)
        await self.session.flush()
        return str(secret["access_token"])

    # --- manual --------------------------------------------------------

    async def create_manual(
        self, *, kind: str, label: str, secret: str, config: dict[str, Any]
    ) -> Connection:
        try:
            kind_enum = ConnectionKind(kind)
        except ValueError as exc:
            raise ValidationError(f"'{kind}' is not a connection type.") from exc
        model = MANUAL_CONFIGS.get(kind_enum)
        if model is None:
            raise ValidationError(f"{kind} is connected with one click, not by hand.")
        await self._require_allowed(kind_enum)
        try:
            clean = model.model_validate(config).model_dump()
        except PydanticValidationError as exc:
            problems = "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in exc.errors())
            raise ValidationError(problems) from exc
        _check_hosts(clean)
        if kind_enum in (ConnectionKind.SLACK, ConnectionKind.TEAMS):
            from app.agent.tools.packs.chat import webhook_problem

            if problem := webhook_problem(kind, secret):
                raise ValidationError(problem)
            secret = secret.strip()

        existing = await self.session.scalar(
            select(Connection).where(
                Connection.owner_id == self.owner_id,
                Connection.kind == kind_enum,
                Connection.label == label,
            )
        )
        conn = existing or Connection(owner_id=self.owner_id, kind=kind_enum, label=label)
        conn.credential_enc = encrypt(secret, scope=self.owner_id)
        conn.credential_last4 = secret[-4:] if len(secret) >= 4 else "????"
        conn.config = clean
        conn.status = STATUS_UNTESTED
        conn.last_error = None
        conn.enabled = True
        if existing is None:
            self.session.add(conn)
        await self.session.flush()
        log.info("connection_manual_saved", owner_id=str(self.owner_id), kind=kind)
        return conn

    # --- test, toggle, remove -----------------------------------------

    async def test(self, connection_id: uuid.UUID) -> Connection:
        conn = await self.get(connection_id)
        try:
            if conn.kind in (ConnectionKind.GOOGLE, ConnectionKind.MICROSOFT):
                provider, _ = await self._provider(conn.kind.value)
                token = await self._fresh_access_token(conn)
                async with _client() as http:
                    resp = await http.get(
                        provider.userinfo_url, headers={"Authorization": f"Bearer {token}"}
                    )
                if resp.status_code == 401:
                    token = await self._fresh_access_token(conn, force=True)
                    async with _client() as http:
                        resp = await http.get(
                            provider.userinfo_url, headers={"Authorization": f"Bearer {token}"}
                        )
                if resp.status_code >= 400:
                    raise ValidationError(f"The provider answered {resp.status_code}.")
            elif conn.kind is ConnectionKind.EMAIL:
                await _test_email(conn.config, decrypt(conn.credential_enc, scope=self.owner_id))
            elif conn.kind is ConnectionKind.DATABASE:
                await _test_database(conn.config, decrypt(conn.credential_enc, scope=self.owner_id))
            elif conn.kind in (ConnectionKind.SLACK, ConnectionKind.TEAMS):
                await _test_channel(
                    conn.kind.value, decrypt(conn.credential_enc, scope=self.owner_id)
                )
            elif conn.kind is ConnectionKind.GITHUB:
                login = await _test_github(decrypt(conn.credential_enc, scope=self.owner_id))
                conn.config = {**(conn.config or {}), "account": login}
            conn.status = STATUS_CONNECTED
            conn.last_error = None
        except Exception as exc:  # noqa: BLE001 - the reason is shown to the person
            if conn.status != STATUS_RECONNECT:
                conn.status = STATUS_FAILED
            conn.last_error = _short(exc)
        conn.last_tested_at = datetime.now(UTC)
        await self.session.flush()
        return conn

    async def set_enabled(self, connection_id: uuid.UUID, enabled: bool) -> Connection:
        conn = await self.get(connection_id)
        conn.enabled = enabled
        await self.session.flush()
        return conn

    async def delete(self, connection_id: uuid.UUID) -> None:
        conn = await self.get(connection_id)
        await self.session.delete(conn)
        await self.session.flush()
        log.info("connection_removed", owner_id=str(self.owner_id), kind=conn.kind.value)

    # --- the worker's read path ---------------------------------------

    async def resolve_grants(self) -> dict[str, Grant]:
        """Every usable connection, one per kind, ready for tools.

        Called by the worker at the start of a run. A connection that
        fails to refresh is skipped, not fatal: the tools that need it
        report "not connected", and the rest of the run carries on.
        """
        rows = await self.session.scalars(
            select(Connection)
            .where(Connection.owner_id == self.owner_id, Connection.enabled.is_(True))
            .order_by(Connection.updated_at.desc())
        )
        grants: dict[str, Grant] = {}
        for conn in rows.all():
            kind = conn.kind.value
            if kind in grants or conn.status == STATUS_RECONNECT:
                continue
            try:
                if conn.kind in (ConnectionKind.GOOGLE, ConnectionKind.MICROSOFT):
                    credential = await self._fresh_access_token(conn)
                else:
                    credential = decrypt(conn.credential_enc, scope=self.owner_id)
            except Exception as exc:  # noqa: BLE001 - one bad connection must not stop a run
                log.warning("connection_unusable", kind=kind, error=_short(exc))
                continue
            public = {k: v for k, v in (conn.config or {}).items() if k != "connected_by"}
            grants[kind] = Grant(credential=credential, config=public)
        return grants


# ------------------------------------------------------------------ helpers


def _short(exc: BaseException) -> str:
    text = getattr(exc, "message", None) or str(exc) or type(exc).__name__
    return str(text)[:300]


def _check_hosts(config: dict[str, Any]) -> None:
    """Outside development, refuse hosts inside our own network.

    Otherwise someone could point a "database connection" at the
    platform's own Postgres or a cloud metadata address, and use the
    agent as a way in.
    """
    if get_settings().environment != "prod":
        return
    from app.core.urls import is_private_address as _is_private_address

    for key in ("host", "imap_host", "smtp_host"):
        host = config.get(key)
        if host and _is_private_address(str(host)):
            raise ValidationError(f"{key} must be a public address.")


async def _test_github(token: str) -> str:
    """Who the token belongs to: proves it works, and names the account."""
    async with _client() as http:
        resp = await http.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
    if resp.status_code == 401:
        raise ValidationError("GitHub refused the token. Check it has not expired.")
    if resp.status_code >= 400:
        raise ValidationError(f"GitHub answered {resp.status_code}.")
    return str(resp.json().get("login") or "")


async def _test_channel(kind: str, url: str) -> None:
    """The only real test of a webhook is a post, so the channel gets one
    short line saying it is connected."""
    from app.agent.tools.packs.chat import ChatPostArgs, SlackPost, TeamsPost, post

    tool = SlackPost() if kind == "slack" else TeamsPost()
    result = await post(
        kind, url, tool.payload(ChatPostArgs(text="Baton is connected to this channel."))
    )
    if not result.ok:
        raise ValidationError(result.message or "The channel did not accept the test message.")


async def _test_email(config: dict[str, Any], password: str) -> None:
    from app.agent.tools.packs.email import _imap

    def check() -> None:
        client = _imap(config, password)
        client.logout()

    await asyncio.wait_for(asyncio.to_thread(check), timeout=HTTP_TIMEOUT_S)


async def _test_database(config: dict[str, Any], password: str) -> None:
    from sqlalchemy import text

    from app.agent.tools.base import ToolContext
    from app.agent.tools.packs.sql import _engine

    engine = _engine(ToolContext(owner_id=uuid.uuid4(), credential=password, config=config))
    try:
        async with asyncio.timeout(HTTP_TIMEOUT_S), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
