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

import pyotp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.core.errors import ConflictError, InvalidCredentialsError, NotFoundError
from app.core.observability import get_logger
from app.core.security import create_access_token, hash_password, hash_token, verify_password
from app.db.models.ai_employee import COUNTS_TOWARD_LIMIT, AIEmployee
from app.db.models.identity import Invitation, Membership, PlatformAdmin, Role
from app.db.models.organization import Organization, OrgStatus
from app.db.models.policy import ConnectionKind
from app.db.models.provider import OrgConnectionAccess, PlatformOAuthApp
from app.db.repositories.identity_repo import OrganizationRepository, PlatformAdminRepository
from app.services.oauth_providers import get_oauth_provider, resolve_client

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


@dataclass(slots=True)
class CompanyStats:
    org: Organization
    member_count: int
    employee_count: int = 0  # populated from phase 2 onward


class PlatformService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.admins = PlatformAdminRepository(session)
        self.orgs = OrganizationRepository(session)
        self.settings = get_settings()

    # ------------------------------------------------------------- admins

    async def create_admin(self, *, email: str, password: str) -> tuple[PlatformAdmin, str]:
        """Create a platform admin and return the TOTP secret once.

        Used by the bootstrap script. The secret is shown exactly here,
        for entering into an authenticator app; afterwards only the
        encrypted form exists.
        """
        email = email.lower()
        if await self.admins.get_by_email(email):
            raise ConflictError("A platform admin with that email already exists.")

        totp_secret = pyotp.random_base32()
        admin = PlatformAdmin(
            email=email,
            password_hash=hash_password(password),
            totp_secret_enc=encrypt(totp_secret, scope="platform"),
            totp_confirmed=True,
        )
        self.session.add(admin)
        await self.session.flush()
        return admin, totp_secret

    async def login(self, *, email: str, password: str, totp_code: str) -> str:
        """Password *and* a valid TOTP code. Both, always.

        This account can create and suspend every company, so a leaked
        password alone must not be enough.
        """
        admin = await self.admins.get_by_email(email)

        if admin is None:
            hash_password(password)  # keep timing similar to a real miss
            raise InvalidCredentialsError()

        if not verify_password(password, admin.password_hash) or not admin.is_active:
            raise InvalidCredentialsError()

        secret = decrypt(admin.totp_secret_enc, scope="platform")
        if not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
            log.warning("platform_admin_totp_failed", admin_id=str(admin.id))
            raise InvalidCredentialsError("Email, password or code is incorrect.")

        admin.last_login_at = datetime.now(UTC)
        self.admins.record_audit(admin_id=admin.id, action="platform_login")

        return create_access_token(
            subject=admin.id,
            token_type="platform_access",  # noqa: S106 - a token kind, not a secret
        )

    # ------------------------------------------------------------- companies

    async def create_company(
        self,
        *,
        admin_id: uuid.UUID,
        name: str,
        slug: str,
        first_admin_email: str,
        max_employees: int,
    ) -> tuple[Organization, str]:
        """Create a company and its first invite.

        There is no public sign-up, so this is how every company begins.
        It is Active immediately — no approval queue, because the
        Platform Admin creating it *is* the approval.
        """
        slug = slug.lower().strip()
        if await self.orgs.get_by_slug(slug):
            raise ConflictError(f"A company with the slug '{slug}' already exists.")

        org = Organization(
            name=name, slug=slug, max_employees=max_employees, status=OrgStatus.ACTIVE
        )
        self.session.add(org)
        await self.session.flush()

        raw_token = secrets.token_urlsafe(32)
        self.session.add(
            Invitation(
                org_id=org.id,
                email=first_admin_email.lower(),
                role=Role.ADMIN,
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(hours=self.settings.invite_expiry_hours),
            )
        )

        self.admins.record_audit(
            admin_id=admin_id,
            action="company_created",
            target_type="organization",
            target_id=str(org.id),
            detail=f"slug={slug} max_employees={max_employees}",
        )
        log.info("company_created", org_id=str(org.id), slug=slug)
        return org, raw_token

    async def list_companies(self) -> list[CompanyStats]:
        """Counts and health only. No customer content.

        Members and AI Employees are counted in separate subqueries
        rather than two joins: joining both at once multiplies the rows
        together, so a company with 2 members and 3 employees would
        report 6 of each.
        """
        member_counts = (
            select(Membership.org_id, func.count().label("members"))
            .group_by(Membership.org_id)
            .subquery()
        )
        employee_counts = (
            select(AIEmployee.org_id, func.count().label("employees"))
            .where(AIEmployee.status.in_(COUNTS_TOWARD_LIMIT))
            .group_by(AIEmployee.org_id)
            .subquery()
        )

        rows = await self.session.execute(
            select(
                Organization,
                func.coalesce(member_counts.c.members, 0),
                func.coalesce(employee_counts.c.employees, 0),
            )
            .outerjoin(member_counts, member_counts.c.org_id == Organization.id)
            .outerjoin(employee_counts, employee_counts.c.org_id == Organization.id)
            .order_by(Organization.created_at)
        )
        return [
            CompanyStats(org=org, member_count=members, employee_count=employees)
            for org, members, employees in rows.all()
        ]

    async def set_status(
        self, *, admin_id: uuid.UUID, org_id: uuid.UUID, status: OrgStatus
    ) -> Organization:
        org = await self.orgs.get(org_id)
        if org is None:
            raise NotFoundError("No such company.")

        org.status = status
        self.admins.record_audit(
            admin_id=admin_id,
            action=f"company_{status.value}",
            target_type="organization",
            target_id=str(org_id),
        )
        return org

    async def set_employee_limit(
        self, *, admin_id: uuid.UUID, org_id: uuid.UUID, max_employees: int
    ) -> Organization:
        org = await self.orgs.get(org_id)
        if org is None:
            raise NotFoundError("No such company.")

        previous = org.max_employees
        org.max_employees = max_employees
        self.admins.record_audit(
            admin_id=admin_id,
            action="employee_limit_changed",
            target_type="organization",
            target_id=str(org_id),
            detail=f"{previous} -> {max_employees}",
        )
        return org

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

    async def connection_access(self, org_id: uuid.UUID) -> list[ConnectionAccessView]:
        from app.services.connection_service import CATALOGUE

        rows = {
            row.kind: row
            for row in (
                await self.session.scalars(
                    select(OrgConnectionAccess).where(OrgConnectionAccess.org_id == org_id)
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
        org_id: uuid.UUID,
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

        if await self.orgs.get(org_id) is None:
            raise NotFoundError("No such company.")

        existing = await self.session.scalar(
            select(OrgConnectionAccess).where(
                OrgConnectionAccess.org_id == org_id,
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
                    org_id=org_id,
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
            target_id=str(org_id),
            detail=kind,
        )
