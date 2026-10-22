"""Platform Admin operations: creating and governing companies.

The boundary that matters: nothing here reads customer content. A
Platform Admin sees how many and how healthy, never what. There is no
method on this service that returns a task, a memory, a credential or a
message — by design, so the capability does not exist to be misused.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.services import EDIT, LEVELS, SERVICES
from app.config import get_settings
from app.core.crypto import encrypt
from app.core.errors import ConflictError, InvalidCredentialsError, NotFoundError
from app.core.observability import get_logger
from app.core.security import create_access_token, hash_password, hash_token, verify_password
from app.db.models.identity import PlatformAdmin, SetupToken, User
from app.db.models.policy import ConnectionKind
from app.db.models.provider import OrgConnectionAccess, PlatformOAuthApp
from app.db.repositories.identity_repo import PlatformAdminRepository, UserRepository
from app.services.oauth_providers import get_oauth_provider, resolve_client
from app.services.service_access_service import ServiceAccessService

log = get_logger(__name__)


@dataclass(slots=True)
class OAuthAppView:
    """What a Platform Admin may see of a registered OAuth app.

    The secret is write-only, like every other credential here: the
    last four characters are enough to tell two keys apart, and there
    is no endpoint that returns more.
    """

    provider: str
    display_name: str
    client_id: str | None
    secret_last4: str | None
    enabled: bool
    configured: bool
    # Where the operator must point the app in Google's or Microsoft's
    # console. Getting this wrong is the single most common reason a
    # one-click sign-in fails, so it is shown rather than documented.
    redirect_uri: str
    docs_url: str
    from_environment: bool


@dataclass(slots=True)
class ConnectionAccessView:
    """One connection, as it stands for one company."""

    kind: str
    display_name: str
    # True when the platform has this connection working at all. A
    # company cannot be granted something nobody has registered.
    platform_ready: bool
    allowed: bool
    # False when no ruling exists and the company simply inherits.
    overridden: bool
    note: str | None


class PlatformService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.admins = PlatformAdminRepository(session)
        self.users = UserRepository(session)
        self.settings = get_settings()

    # ------------------------------------------------------------- admins

    async def create_admin(self, *, email: str, password: str) -> PlatformAdmin:
        """Create a platform admin. Used by the bootstrap script."""
        email = email.lower()
        if await self.admins.get_by_email(email):
            raise ConflictError("A platform admin with that email already exists.")

        admin = PlatformAdmin(
            email=email,
            password_hash=hash_password(password),
        )
        self.session.add(admin)
        await self.session.flush()
        return admin

    async def login(self, *, email: str, password: str) -> str:
        """Password only.

        Second-factor was removed on request. Worth being plain about
        what that costs: this account can create and suspend every
        company on the platform, so a single leaked or guessed password
        is now enough to reach all of them. The compensating controls
        are what remain — the separate token type, the append-only
        audit log, and the fact that no platform endpoint returns
        customer content.
        """
        admin = await self.admins.get_by_email(email)

        if admin is None:
            hash_password(password)  # keep timing similar to a real miss
            raise InvalidCredentialsError()

        if not verify_password(password, admin.password_hash) or not admin.is_active:
            raise InvalidCredentialsError()

        admin.last_login_at = datetime.now(UTC)
        self.admins.record_audit(admin_id=admin.id, action="platform_login")

        return create_access_token(
            subject=admin.id,
            token_type="platform_access",  # noqa: S106 - a token kind, not a secret
        )

    # ------------------------------------------------------------- companies

    async def create_person(
        self,
        *,
        admin_id: uuid.UUID,
        email: str,
        full_name: str | None,
    ) -> tuple[User, str]:
        """Create an account and the link its owner signs in with.

        The password is set by the person themselves through that
        link, so a Platform Admin never knows it and cannot sign in as
        anybody. The account is usable immediately — the admin
        creating it is the approval.
        """
        email = email.lower().strip()
        if await self.users.get_by_email(email):
            raise ConflictError(f"An account for {email} already exists.")

        raw_token = secrets.token_urlsafe(32)
        user = User(
            email=email,
            full_name=full_name,
            # A placeholder nobody can produce: the account is unusable
            # until the setup link sets a real one.
            password_hash=hash_password(secrets.token_urlsafe(32)),
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()

        self.session.add(
            SetupToken(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(hours=self.settings.invite_expiry_hours),
            )
        )

        self.admins.record_audit(
            admin_id=admin_id,
            action="account_created",
            target_type="user",
            target_id=str(user.id),
        )
        log.info("account_created", user_id=str(user.id))
        return user, raw_token

    async def list_people(self) -> list[User]:
        """Every account. Who they are and whether they are active; nothing
        about what they have done, because no endpoint returns that."""
        rows = await self.session.scalars(select(User).order_by(User.created_at))
        return list(rows.all())

    async def set_active(self, *, admin_id: uuid.UUID, owner_id: uuid.UUID, active: bool) -> User:
        """Suspend or restore an account.

        Their work is untouched: a suspended person cannot sign in,
        and nothing of theirs is read or deleted here.
        """
        user = await self._person(owner_id)
        user.is_active = active
        self.admins.record_audit(
            admin_id=admin_id,
            action="account_restored" if active else "account_suspended",
            target_type="user",
            target_id=str(owner_id),
        )
        return user

    async def _person(self, owner_id: uuid.UUID) -> User:
        user = await self.users.get(owner_id)
        if user is None:
            raise NotFoundError("No such account.")
        return user

    # --- the one-click OAuth apps -------------------------------------

    OAUTH_DOCS: ClassVar[dict[str, str]] = {
        "google": "https://console.cloud.google.com/apis/credentials",
        "microsoft": "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps",
    }

    async def oauth_apps(self) -> list[OAuthAppView]:
        """Every provider that supports one-click, set up or not.

        Providers with nothing registered are still listed: the point
        of this screen is to show an operator what is *missing*, and a
        provider that vanishes when unset cannot be turned on.
        """
        rows = {
            app.provider: app
            for app in (await self.session.scalars(select(PlatformOAuthApp))).all()
        }

        out: list[OAuthAppView] = []
        for kind in (ConnectionKind.GOOGLE, ConnectionKind.MICROSOFT):
            provider = get_oauth_provider(kind.value)
            if provider is None:
                continue

            app = rows.get(kind)
            env = provider.client_from_env() if app is None else None
            from_env = env is not None
            out.append(
                OAuthAppView(
                    provider=kind.value,
                    display_name=provider.display_name,
                    client_id=app.client_id if app else (env[0] if env else None),
                    secret_last4=app.secret_last4 if app else None,
                    enabled=app.enabled if app else from_env,
                    configured=(app.enabled if app else False) or from_env,
                    redirect_uri=provider.redirect_uri(),
                    docs_url=self.OAUTH_DOCS[kind.value],
                    from_environment=from_env,
                )
            )
        return out

    async def save_oauth_app(
        self,
        *,
        admin_id: uuid.UUID,
        provider_key: str,
        client_id: str,
        client_secret: str,
    ) -> PlatformOAuthApp:
        provider = get_oauth_provider(provider_key)
        if provider is None:
            raise NotFoundError(f"'{provider_key}' does not support one-click connection.")

        kind = provider.kind
        app = await self.session.scalar(
            select(PlatformOAuthApp).where(PlatformOAuthApp.provider == kind)
        )

        # Encrypted under the platform scope, not a company's: the app
        # belongs to the platform, and every company signs in through it.
        ciphertext = encrypt(client_secret, scope="platform")
        last4 = client_secret[-4:] if len(client_secret) >= 4 else "????"

        if app is None:
            app = PlatformOAuthApp(
                provider=kind,
                client_id=client_id,
                client_secret_enc=ciphertext,
                secret_last4=last4,
                enabled=True,
                updated_by=admin_id,
            )
            self.session.add(app)
            action = "oauth_app_registered"
        else:
            app.client_id = client_id
            app.client_secret_enc = ciphertext
            app.secret_last4 = last4
            app.enabled = True
            app.updated_by = admin_id
            action = "oauth_app_updated"

        self.admins.record_audit(
            admin_id=admin_id,
            action=action,
            target_type="oauth_app",
            target_id=kind.value,
            # The id, never the secret. This log is readable by every
            # Platform Admin and is deliberately append-only.
            detail=f"client_id {client_id[:12]}…",
        )
        return app

    async def set_oauth_app_enabled(
        self, *, admin_id: uuid.UUID, provider_key: str, enabled: bool
    ) -> PlatformOAuthApp:
        app = await self._oauth_app(provider_key)
        app.enabled = enabled
        app.updated_by = admin_id
        self.admins.record_audit(
            admin_id=admin_id,
            action="oauth_app_enabled" if enabled else "oauth_app_disabled",
            target_type="oauth_app",
            target_id=provider_key,
        )
        return app

    async def delete_oauth_app(self, *, admin_id: uuid.UUID, provider_key: str) -> None:
        app = await self._oauth_app(provider_key)
        await self.session.delete(app)
        self.admins.record_audit(
            admin_id=admin_id,
            action="oauth_app_removed",
            target_type="oauth_app",
            target_id=provider_key,
        )

    async def _oauth_app(self, provider_key: str) -> PlatformOAuthApp:
        provider = get_oauth_provider(provider_key)
        app = (
            await self.session.scalar(
                select(PlatformOAuthApp).where(PlatformOAuthApp.provider == provider.kind)
            )
            if provider
            else None
        )
        if app is None:
            raise NotFoundError(f"No OAuth app is registered for '{provider_key}'.")
        return app

    # --- which connections a company may use --------------------------

    async def connection_access(self, owner_id: uuid.UUID) -> list[ConnectionAccessView]:
        from app.services.connection_service import CATALOGUE

        rows = {
            row.kind: row
            for row in (
                await self.session.scalars(
                    select(OrgConnectionAccess).where(OrgConnectionAccess.owner_id == owner_id)
                )
            ).all()
        }

        out: list[ConnectionAccessView] = []
        for kind, meta in CATALOGUE.items():
            provider = get_oauth_provider(kind.value)
            ready = (
                await resolve_client(self.session, provider) is not None
                if provider is not None
                else True
            )
            ruling = rows.get(kind)
            out.append(
                ConnectionAccessView(
                    kind=kind.value,
                    display_name=str(meta["display_name"]),
                    platform_ready=ready,
                    allowed=ruling.allowed if ruling else True,
                    overridden=ruling is not None,
                    note=ruling.note if ruling else None,
                )
            )
        return out

    async def set_connection_access(
        self,
        *,
        admin_id: uuid.UUID,
        owner_id: uuid.UUID,
        kind: str,
        allowed: bool | None,
        note: str | None = None,
    ) -> None:
        """Open or close one connection for one company.

        `allowed=None` removes the ruling and returns the company to
        inheriting the platform default, which is a different state
        from "allowed" and worth being able to get back to.
        """
        from app.db.models.policy import ConnectionKind
        from app.services.connection_service import CATALOGUE

        try:
            kind_enum = ConnectionKind(kind)
        except ValueError as exc:
            raise NotFoundError(f"'{kind}' is not a connection type.") from exc
        if kind_enum not in CATALOGUE:
            raise NotFoundError(f"'{kind}' is not a connection type.")

        await self._person(owner_id)

        existing = await self.session.scalar(
            select(OrgConnectionAccess).where(
                OrgConnectionAccess.owner_id == owner_id,
                OrgConnectionAccess.kind == kind_enum,
            )
        )

        if allowed is None:
            if existing is not None:
                await self.session.delete(existing)
            action = "connection_access_inherited"
        elif existing is None:
            self.session.add(
                OrgConnectionAccess(
                    owner_id=owner_id,
                    kind=kind_enum,
                    allowed=allowed,
                    note=note,
                    updated_by=admin_id,
                )
            )
            action = "connection_allowed" if allowed else "connection_blocked"
        else:
            existing.allowed = allowed
            existing.note = note
            existing.updated_by = admin_id
            action = "connection_allowed" if allowed else "connection_blocked"

        self.admins.record_audit(
            admin_id=admin_id,
            action=action,
            target_type="organization",
            target_id=str(owner_id),
            detail=kind,
        )

    # --- service access: which parts of an app, read or edit ----------------

    async def service_matrix(self) -> list[ServiceAccessView]:
        """What the platform allows for every part of every app."""
        platform = await ServiceAccessService(self.session).platform_matrix()
        return [
            ServiceAccessView(
                service=sid,
                app=SERVICES[sid].app,
                name=SERVICES[sid].name,
                level=level,
                allowed=allowed,
            )
            for (sid, level), allowed in platform.items()
        ]

    async def set_platform_service(
        self, *, admin_id: uuid.UUID, service: str, level: str, allowed: bool
    ) -> None:
        await ServiceAccessService(self.session).set_platform(
            service, level, allowed, admin_id=admin_id
        )
        self.admins.record_audit(
            admin_id=admin_id,
            action="service_allowed" if allowed else "service_blocked",
            target_type="platform",
            detail=f"{service}:{level}",
        )

    async def company_services(self, owner_id: uuid.UUID) -> list[CompanyServiceView]:
        """Per service and level: what this company gets, and whether that
        is its own ruling or inherited from the platform."""
        await self._person(owner_id)
        rules = ServiceAccessService(self.session, owner_id)
        snapshot = await rules.snapshot()
        out: list[CompanyServiceView] = []
        for sid, svc in SERVICES.items():
            for level in LEVELS:
                if level == EDIT and not svc.has_edit:
                    continue
                own = snapshot.company.get((sid, level))
                decision = snapshot.decide(sid, level)
                out.append(
                    CompanyServiceView(
                        service=sid,
                        app=svc.app,
                        name=svc.name,
                        level=level,
                        allowed=decision.allowed,
                        overridden=own is not None,
                        note=own.note if own else None,
                    )
                )
        return out

    async def set_company_service(
        self,
        *,
        admin_id: uuid.UUID,
        owner_id: uuid.UUID,
        service: str,
        level: str,
        allowed: bool | None,
        note: str | None = None,
    ) -> None:
        """`allowed=None` removes the company's ruling, so it inherits the
        platform's again."""
        await self._person(owner_id)
        await ServiceAccessService(self.session, owner_id).set_company(
            owner_id, service, level, allowed, note=note, admin_id=admin_id
        )
        self.admins.record_audit(
            admin_id=admin_id,
            action=(
                "service_inherited"
                if allowed is None
                else "service_allowed"
                if allowed
                else "service_blocked"
            ),
            target_type="organization",
            target_id=str(owner_id),
            detail=f"{service}:{level}",
        )


@dataclass(slots=True)
class ServiceAccessView:
    service: str
    app: str
    name: str
    level: str
    allowed: bool


@dataclass(slots=True)
class CompanyServiceView:
    service: str
    app: str
    name: str
    level: str
    allowed: bool
    overridden: bool
    note: str | None
