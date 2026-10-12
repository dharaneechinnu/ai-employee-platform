"""Connections: the outside apps a company lets its AI Employees use.

Two ways in:

- **One click (OAuth)** for Google and Microsoft. The admin signs in
  with their provider, approves the listed permissions, and we keep the
  refresh token. Nobody pastes a password.
- **Manual** for a mailbox over IMAP/SMTP or a PostgreSQL database,
  where the secret is an app password or a read-only database password.

Either way the secret is handled like a provider key: encrypted with
the company's own key, never returned by any endpoint, and never placed
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
from app.core.errors import NotFoundError, ValidationError
from app.core.observability import get_logger
from app.core.signed import InvalidSignedTokenError, sign_for, verify
from app.db.models.policy import Connection, ConnectionKind
from app.services.oauth_providers import OAuthProvider, get_oauth_provider

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


MANUAL_CONFIGS: dict[ConnectionKind, type[BaseModel]] = {
    ConnectionKind.EMAIL: EmailConfig,
    ConnectionKind.DATABASE: DatabaseConfig,
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


# ------------------------------------------------------------------ service


class ConnectionService:
    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        self.session = session
        self.org_id = org_id

    # --- reading -------------------------------------------------------

    def available(self) -> list[AvailableConnection]:
        out: list[AvailableConnection] = []
        for kind, meta in CATALOGUE.items():
            oauth = get_oauth_provider(kind.value)
            out.append(
                AvailableConnection(
                    kind=kind.value,
                    display_name=meta["display_name"],
                    description=meta["description"],
                    auth=meta["auth"],
                    apps=meta["apps"],
                    configured=oauth.client() is not None if oauth else True,
                    tools=tools_for(kind.value),
                    fields=meta.get("fields", []),
                    secret_label=meta.get("secret_label"),
                )
            )
        return out

    async def list_all(self) -> list[ConnectionView]:
        rows = await self.session.scalars(
            select(Connection)
            .where(Connection.org_id == self.org_id)
            .order_by(Connection.kind, Connection.created_at)
        )
        return [self._view(c) for c in rows.all()]

    async def get(self, connection_id: uuid.UUID) -> Connection:
        conn = await self.session.scalar(
            select(Connection).where(
                Connection.id == connection_id, Connection.org_id == self.org_id
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

    # --- one click (OAuth) --------------------------------------------

    def _provider(self, kind: str) -> tuple[OAuthProvider, tuple[str, str]]:
        provider = get_oauth_provider(kind)
        if provider is None:
            raise ValidationError(f"'{kind}' does not support one-click connection.")
        client = provider.client()
        if client is None:
            raise ValidationError(
                f"{provider.display_name} sign-in is not set up on this platform yet. "
                "The platform operator needs to add its OAuth client id and secret."
            )
        return provider, client

    def start_oauth(self, kind: str, *, user_id: uuid.UUID) -> str:
        provider, (client_id, _) = self._provider(kind)
        # The state is signed, so the callback can trust which company
        # and person started this without a table of pending sign-ins.
        state = sign_for(
            "oauth_state",
            {"org": str(self.org_id), "sub": str(user_id), "kind": provider.kind.value},
            minutes=STATE_MINUTES,
        )
        return provider.authorize(client_id=client_id, state=state)

    @staticmethod
    def read_state(state: str, kind: str) -> tuple[uuid.UUID, uuid.UUID]:
        """(org_id, user_id) from a callback's state, or raise."""
        try:
            claims = verify(state, "oauth_state")
            if claims.get("kind") != kind:
                raise InvalidSignedTokenError("This sign-in was started for another provider.")
            return uuid.UUID(claims["org"]), uuid.UUID(claims["sub"])
        except (KeyError, ValueError) as exc:
            raise InvalidSignedTokenError("This sign-in link is not valid.") from exc

    async def complete_oauth(self, kind: str, *, code: str, user_id: uuid.UUID) -> Connection:
        provider, (client_id, client_secret) = self._provider(kind)

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
                Connection.org_id == self.org_id,
                Connection.kind == provider.kind,
                Connection.label == account,
            )
        )

        refresh_token = tokens.get("refresh_token")
        if not refresh_token and existing is not None:
            # Reconnecting the same account: some providers only issue a
            # refresh token on the first consent. Keep the one we have.
            refresh_token = json.loads(decrypt(existing.credential_enc, scope=self.org_id)).get(
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

        conn = existing or Connection(org_id=self.org_id, kind=provider.kind, label=account[:100])
        conn.credential_enc = encrypt(json.dumps(secret), scope=self.org_id)
        conn.credential_last4 = refresh_token[-4:]
        conn.config = config
        conn.status = STATUS_CONNECTED
        conn.last_tested_at = datetime.now(UTC)
        conn.last_error = None
        conn.enabled = True
        if existing is None:
            self.session.add(conn)
        await self.session.flush()
        log.info("connection_oauth_connected", org_id=str(self.org_id), kind=kind)
        return conn

    async def _fresh_access_token(self, conn: Connection, *, force: bool = False) -> str:
        """The stored access token, refreshed first if it is close to
        expiring. A refresh that the provider rejects means the company
        revoked access, so the connection is marked for reconnecting."""
        secret = json.loads(decrypt(conn.credential_enc, scope=self.org_id))
        if not force and secret.get("expires_at", 0) - time.time() > REFRESH_MARGIN_S:
            return str(secret["access_token"])

        provider, (client_id, client_secret) = self._provider(conn.kind.value)
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
        conn.credential_enc = encrypt(json.dumps(secret), scope=self.org_id)
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
        try:
            clean = model.model_validate(config).model_dump()
        except PydanticValidationError as exc:
            problems = "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in exc.errors())
            raise ValidationError(problems) from exc
        _check_hosts(clean)

        existing = await self.session.scalar(
            select(Connection).where(
                Connection.org_id == self.org_id,
                Connection.kind == kind_enum,
                Connection.label == label,
            )
        )
        conn = existing or Connection(org_id=self.org_id, kind=kind_enum, label=label)
        conn.credential_enc = encrypt(secret, scope=self.org_id)
        conn.credential_last4 = secret[-4:] if len(secret) >= 4 else "????"
        conn.config = clean
        conn.status = STATUS_UNTESTED
        conn.last_error = None
        conn.enabled = True
        if existing is None:
            self.session.add(conn)
        await self.session.flush()
        log.info("connection_manual_saved", org_id=str(self.org_id), kind=kind)
        return conn

    # --- test, toggle, remove -----------------------------------------

    async def test(self, connection_id: uuid.UUID) -> Connection:
        conn = await self.get(connection_id)
        try:
            if conn.kind in (ConnectionKind.GOOGLE, ConnectionKind.MICROSOFT):
                provider, _ = self._provider(conn.kind.value)
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
                await _test_email(conn.config, decrypt(conn.credential_enc, scope=self.org_id))
            elif conn.kind is ConnectionKind.DATABASE:
                await _test_database(conn.config, decrypt(conn.credential_enc, scope=self.org_id))
            conn.status = STATUS_CONNECTED
            conn.last_error = None
        except Exception as exc:  # noqa: BLE001 - the reason is shown to the admin
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
        log.info("connection_removed", org_id=str(self.org_id), kind=conn.kind.value)

    # --- the worker's read path ---------------------------------------

    async def resolve_grants(self) -> dict[str, Grant]:
        """Every usable connection, one per kind, ready for tools.

        Called by the worker at the start of a run. A connection that
        fails to refresh is skipped, not fatal: the tools that need it
        report "not connected", and the rest of the run carries on.
        """
        rows = await self.session.scalars(
            select(Connection)
            .where(Connection.org_id == self.org_id, Connection.enabled.is_(True))
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
                    credential = decrypt(conn.credential_enc, scope=self.org_id)
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

    Otherwise a company could point a "database connection" at the
    platform's own Postgres or a cloud metadata address, and use the
    agent as a way in.
    """
    if get_settings().environment != "prod":
        return
    from app.agent.tools.packs.web import _is_private_address

    for key in ("host", "imap_host", "smtp_host"):
        host = config.get(key)
        if host and _is_private_address(str(host)):
            raise ValidationError(f"{key} must be a public address.")


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

    engine = _engine(ToolContext(org_id=uuid.uuid4(), credential=password, config=config))
    try:
        async with asyncio.timeout(HTTP_TIMEOUT_S), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
