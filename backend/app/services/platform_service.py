"""Platform Admin operations: creating and governing personal accounts.

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

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.services import EDIT, LEVELS, SERVICES
from app.config import get_settings
from app.core.crypto import encrypt
from app.core.errors import ConflictError, InvalidCredentialsError, NotFoundError
from app.core.observability import get_logger
from app.core.security import create_access_token, hash_password, hash_token, verify_password
from app.core.usernames import username_from_email
from app.db.models.agent import Agent
from app.db.models.identity import PlatformAdmin, RefreshToken, SetupToken, User
from app.db.models.policy import Connection, ConnectionKind
from app.db.models.provider import (
    PersonConnectionAccess,
    PersonServiceAccess,
    PlatformConnectionAccess,
    PlatformOAuthApp,
    ProviderConfig,
    ProviderKind,
    SupportedProvider,
)
from app.db.models.task import Run
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
    # When it was last saved here, and by which staff member.
    updated_at: datetime | None = None
    updated_by_email: str | None = None


@dataclass(slots=True)
class ConnectionAccessView:
    """One connection, as it stands for one person."""

    kind: str
    display_name: str
    # True when the platform has this connection working at all. A
    # person cannot be granted something nobody has registered.
    platform_ready: bool
    allowed: bool
    # False when no ruling exists and the person simply inherits.
    overridden: bool
    note: str | None
    # What everyone gets, so "Same as everyone" can say what that is.
    everyone_allowed: bool = True


# "This week" everywhere on the staff console means the last seven days,
# not since Monday, so the number does not fall to zero every week.
WEEK = timedelta(days=7)


@dataclass(slots=True)
class PersonFacts:
    """How someone joined and when they were last around. No content.

    `joined_via` is "invited" when a Platform Admin made the account
    (it has a setup link), otherwise "self". `setup_link` is "waiting",
    "used" or "expired" for an invited account, and None for a self
    sign-up.

    `last_active_at` is the later of their last sign-in and the last
    time their session was renewed. The app renews a session every few
    minutes while it is open, so this tracks "was using Baton" without
    reading anything they did. A scheduled agent running on its own
    does not count: that is the agent being active, not the person.
    """

    joined_via: str = "self"
    setup_link: str | None = None
    setup_link_expires_at: datetime | None = None
    last_active_at: datetime | None = None


@dataclass(slots=True)
class PersonCounts:
    """How much someone has built and run. Numbers and yes or no only."""

    agent_count: int = 0
    scheduled_agent_count: int = 0
    runs_this_week: int = 0
    # Connection kind -> whether they have at least one connected.
    apps: dict[str, bool] | None = None


@dataclass(slots=True)
class Overview:
    """The headline numbers. Counts only."""

    people_total: int
    people_active: int
    people_suspended: int
    joined_this_week_self: int
    joined_this_week_invited: int
    setup_links_waiting: int
    # Waiting links that stop working within the next 24 hours.
    setup_links_expiring_soon: int
    ai_keys_total: int
    ai_keys_free: int
    ai_keys_paid: int
    agents_built: int
    runs_this_week: int


@dataclass(slots=True)
class AppAccessView:
    """One kind of app, as it stands for everyone."""

    kind: str
    display_name: str
    platform_ready: bool
    allowed: bool
    people_connected: int
    # People with their own ruling on this app or on any part of it.
    people_with_own_settings: int


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
        account on the platform, so a single leaked or guessed password
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
            ttl=timedelta(hours=get_settings().platform_session_hours),
        )

    # ------------------------------------------------------------- accounts

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
            username=await self.users.free_username(username_from_email(email)),
            full_name=full_name,
            # A placeholder nobody can produce: the account is unusable
            # until the setup link sets a real one.
            password_hash=hash_password(secrets.token_urlsafe(32)),
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()

        expiry = timedelta(hours=self.settings.setup_link_expiry_hours)
        self.session.add(
            SetupToken(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + expiry,
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

    async def set_active(
        self,
        *,
        admin_id: uuid.UUID,
        owner_id: uuid.UUID,
        active: bool,
        reason: str | None = None,
    ) -> User:
        """Suspend or restore an account.

        Their work is untouched: a suspended person cannot sign in,
        and nothing of theirs is read or deleted here. The optional
        reason is staff's own words and goes into the audit entry, so
        the next person to look knows why.
        """
        user = await self._person(owner_id)
        user.is_active = active
        self.admins.record_audit(
            admin_id=admin_id,
            action="account_restored" if active else "account_suspended",
            target_type="user",
            target_id=str(owner_id),
            detail=(reason or "").strip()[:500] or None,
        )
        return user

    async def reissue_setup_link(self, *, admin_id: uuid.UUID, owner_id: uuid.UUID) -> str:
        """A fresh setup link for an invited account nobody has set up yet.

        Only the hash of a link is stored, so the old one cannot be shown
        again; this makes a new one and ends the old. It is refused once
        the account has a password of its own: a link sets the password,
        so handing staff one for a live account would let them sign in
        as that person.
        """
        await self._person(owner_id)
        links = (
            await self.session.scalars(select(SetupToken).where(SetupToken.user_id == owner_id))
        ).all()
        if not links:
            raise ConflictError("This person signed up themselves, so there is no setup link.")
        if any(link.used_at is not None for link in links):
            raise ConflictError("This person has already set their password.")

        now = datetime.now(UTC)
        for link in links:
            if link.expires_at > now:
                link.expires_at = now

        raw_token = secrets.token_urlsafe(32)
        self.session.add(
            SetupToken(
                user_id=owner_id,
                token_hash=hash_token(raw_token),
                expires_at=now + timedelta(hours=self.settings.setup_link_expiry_hours),
            )
        )
        self.admins.record_audit(
            admin_id=admin_id,
            action="setup_link_reissued",
            target_type="user",
            target_id=str(owner_id),
        )
        return raw_token

    # --- what staff may know about people: facts and counts ----------

    async def people_facts(
        self, owner_ids: list[uuid.UUID] | None = None
    ) -> dict[uuid.UUID, PersonFacts]:
        """How each person joined and when they were last active."""
        links = select(
            SetupToken.user_id,
            func.bool_or(SetupToken.used_at.is_not(None)),
            func.max(SetupToken.expires_at),
        ).group_by(SetupToken.user_id)
        sessions = select(RefreshToken.user_id, func.max(RefreshToken.created_at)).group_by(
            RefreshToken.user_id
        )
        users = select(User.id, User.last_login_at)
        if owner_ids is not None:
            links = links.where(SetupToken.user_id.in_(owner_ids))
            sessions = sessions.where(RefreshToken.user_id.in_(owner_ids))
            users = users.where(User.id.in_(owner_ids))

        now = datetime.now(UTC)
        out: dict[uuid.UUID, PersonFacts] = {}
        renewed = dict((await self.session.execute(sessions)).all())
        for uid, last_login in (await self.session.execute(users)).all():
            seen = [t for t in (last_login, renewed.get(uid)) if t is not None]
            out[uid] = PersonFacts(last_active_at=max(seen) if seen else None)
        for uid, used, expires in (await self.session.execute(links)).all():
            facts = out.setdefault(uid, PersonFacts())
            facts.joined_via = "invited"
            if used:
                facts.setup_link = "used"
            else:
                facts.setup_link = "waiting" if expires > now else "expired"
                facts.setup_link_expires_at = expires
        return out

    async def person_counts(self, owner_id: uuid.UUID) -> PersonCounts:
        """Agents built, runs this week, and which apps are connected."""
        agents, scheduled = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count().filter(Agent.schedule_enabled.is_(True)),
                ).where(Agent.owner_id == owner_id, Agent.archived.is_(False))
            )
        ).one()
        runs = await self.session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.owner_id == owner_id, Run.created_at >= datetime.now(UTC) - WEEK)
        )
        connected = set(
            (
                await self.session.scalars(
                    select(Connection.kind).where(Connection.owner_id == owner_id).distinct()
                )
            ).all()
        )
        from app.services.connection_service import CATALOGUE

        return PersonCounts(
            agent_count=agents or 0,
            scheduled_agent_count=scheduled or 0,
            runs_this_week=runs or 0,
            apps={kind.value: kind in connected for kind in CATALOGUE},
        )

    async def overview(self) -> Overview:
        """The numbers on the landing page. Counts only, never content."""
        now = datetime.now(UTC)
        total, active = (
            await self.session.execute(
                select(func.count(), func.count().filter(User.is_active.is_(True)))
            )
        ).one()

        facts = await self.people_facts()
        recent = set(
            (await self.session.scalars(select(User.id).where(User.created_at >= now - WEEK))).all()
        )
        invited_recent = sum(
            1 for uid in recent if facts.get(uid, PersonFacts()).joined_via == "invited"
        )
        waiting = [f for f in facts.values() if f.setup_link == "waiting"]

        # A key's plan is what the person said ("free" or "paid"). When
        # they said nothing, a provider with a free tier or one running
        # on their own machine counts as free.
        free_case = case(
            (ProviderConfig.plan == "free", 1),
            (ProviderConfig.plan == "paid", 0),
            (SupportedProvider.free_tier.is_(True) | SupportedProvider.is_local.is_(True), 1),
            else_=0,
        )
        keys, free = (
            await self.session.execute(
                select(func.count(), func.coalesce(func.sum(free_case), 0))
                .select_from(ProviderConfig)
                .join(SupportedProvider, SupportedProvider.key == ProviderConfig.provider_key)
                .where(
                    ProviderConfig.owner_id.is_not(None),
                    SupportedProvider.kind == ProviderKind.LLM,
                )
            )
        ).one()

        agents = await self.session.scalar(
            select(func.count()).select_from(Agent).where(Agent.archived.is_(False))
        )
        runs = await self.session.scalar(
            select(func.count()).select_from(Run).where(Run.created_at >= now - WEEK)
        )
        return Overview(
            people_total=total or 0,
            people_active=active or 0,
            people_suspended=(total or 0) - (active or 0),
            joined_this_week_self=len(recent) - invited_recent,
            joined_this_week_invited=invited_recent,
            setup_links_waiting=len(waiting),
            setup_links_expiring_soon=sum(
                1
                for f in waiting
                if f.setup_link_expires_at is not None
                and f.setup_link_expires_at <= now + timedelta(hours=24)
            ),
            ai_keys_total=keys or 0,
            ai_keys_free=int(free or 0),
            ai_keys_paid=(keys or 0) - int(free or 0),
            agents_built=agents or 0,
            runs_this_week=runs or 0,
        )

    async def people_per_provider(self) -> dict[str, int]:
        """How many people have connected each AI provider. A count, no keys."""
        rows = await self.session.execute(
            select(ProviderConfig.provider_key, func.count(distinct(ProviderConfig.owner_id)))
            .where(ProviderConfig.owner_id.is_not(None))
            .group_by(ProviderConfig.provider_key)
        )
        return dict(rows.all())

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
        staff = dict(
            (await self.session.execute(select(PlatformAdmin.id, PlatformAdmin.email))).all()
        )

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
                    updated_at=app.updated_at if app else None,
                    updated_by_email=staff.get(app.updated_by) if app and app.updated_by else None,
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

        # Encrypted under the platform scope, not a person's: the app
        # belongs to the platform, and everyone signs in through it.
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

    # --- which connections a person may use ---------------------------

    async def connection_access(self, owner_id: uuid.UUID) -> list[ConnectionAccessView]:
        from app.services.connection_service import CATALOGUE

        rows = {
            row.kind: row
            for row in (
                await self.session.scalars(
                    select(PersonConnectionAccess).where(
                        PersonConnectionAccess.owner_id == owner_id
                    )
                )
            ).all()
        }

        everyone = await self._everyone_apps()
        out: list[ConnectionAccessView] = []
        for kind, meta in CATALOGUE.items():
            provider = get_oauth_provider(kind.value)
            ready = (
                await resolve_client(self.session, provider) is not None
                if provider is not None
                else True
            )
            ruling = rows.get(kind)
            default = everyone.get(kind, True)
            out.append(
                ConnectionAccessView(
                    kind=kind.value,
                    display_name=str(meta["display_name"]),
                    platform_ready=ready,
                    allowed=ruling.allowed if ruling else default,
                    overridden=ruling is not None,
                    note=ruling.note if ruling else None,
                    everyone_allowed=default,
                )
            )
        return out

    async def _everyone_apps(self) -> dict[ConnectionKind, bool]:
        rows = await self.session.scalars(select(PlatformConnectionAccess))
        return {row.kind: row.allowed for row in rows.all()}

    # --- which kinds of app everyone may connect ------------------------

    async def app_access(self) -> list[AppAccessView]:
        """Every kind of app, whether it is open to everyone, and how many
        people use it. Counts only."""
        from app.agent.services import SERVICES
        from app.services.connection_service import CATALOGUE

        everyone = await self._everyone_apps()
        connected = dict(
            (
                await self.session.execute(
                    select(Connection.kind, func.count(distinct(Connection.owner_id))).group_by(
                        Connection.kind
                    )
                )
            ).all()
        )
        own_app = {
            kind: set(owners)
            for kind, owners in (
                await self.session.execute(
                    select(
                        PersonConnectionAccess.kind, func.array_agg(PersonConnectionAccess.owner_id)
                    ).group_by(PersonConnectionAccess.kind)
                )
            ).all()
        }
        for service, owner in (
            await self.session.execute(
                select(PersonServiceAccess.service, PersonServiceAccess.owner_id).distinct()
            )
        ).all():
            svc = SERVICES.get(service)
            if svc is not None:
                own_app.setdefault(ConnectionKind(svc.app), set()).add(owner)

        out: list[AppAccessView] = []
        for kind, meta in CATALOGUE.items():
            provider = get_oauth_provider(kind.value)
            out.append(
                AppAccessView(
                    kind=kind.value,
                    display_name=str(meta["display_name"]),
                    platform_ready=(
                        await resolve_client(self.session, provider) is not None
                        if provider is not None
                        else True
                    ),
                    allowed=everyone.get(kind, True),
                    people_connected=connected.get(kind, 0),
                    people_with_own_settings=len(own_app.get(kind, set())),
                )
            )
        return out

    async def set_app_access(self, *, admin_id: uuid.UUID, kind: str, allowed: bool) -> None:
        """Open or close one kind of app for everyone.

        People with their own ruling keep it; everyone else follows
        this. Nobody's existing connection is deleted: a closed app
        simply cannot be connected or used until it is opened again.
        """
        from app.services.connection_service import CATALOGUE

        try:
            kind_enum = ConnectionKind(kind)
        except ValueError as exc:
            raise NotFoundError(f"'{kind}' is not a connection type.") from exc
        if kind_enum not in CATALOGUE:
            raise NotFoundError(f"'{kind}' is not a connection type.")

        row = await self.session.scalar(
            select(PlatformConnectionAccess).where(PlatformConnectionAccess.kind == kind_enum)
        )
        if row is None:
            self.session.add(
                PlatformConnectionAccess(kind=kind_enum, allowed=allowed, updated_by=admin_id)
            )
        else:
            row.allowed, row.updated_by = allowed, admin_id
        self.admins.record_audit(
            admin_id=admin_id,
            action="app_allowed" if allowed else "app_blocked",
            target_type="platform",
            detail=kind,
        )

    async def set_connection_access(
        self,
        *,
        admin_id: uuid.UUID,
        owner_id: uuid.UUID,
        kind: str,
        allowed: bool | None,
        note: str | None = None,
    ) -> None:
        """Open or close one connection for one person.

        `allowed=None` removes the ruling and returns the person to
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
            select(PersonConnectionAccess).where(
                PersonConnectionAccess.owner_id == owner_id,
                PersonConnectionAccess.kind == kind_enum,
            )
        )

        if allowed is None:
            if existing is not None:
                await self.session.delete(existing)
            action = "connection_access_inherited"
        elif existing is None:
            self.session.add(
                PersonConnectionAccess(
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
            target_type="user",
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

    async def person_services(self, owner_id: uuid.UUID) -> list[PersonServiceView]:
        """Per service and level: what this person gets, and whether that
        is their own ruling or inherited from the platform."""
        await self._person(owner_id)
        rules = ServiceAccessService(self.session, owner_id)
        snapshot = await rules.snapshot()
        out: list[PersonServiceView] = []
        for sid, svc in SERVICES.items():
            for level in LEVELS:
                if level == EDIT and not svc.has_edit:
                    continue
                own = snapshot.person.get((sid, level))
                decision = snapshot.decide(sid, level)
                out.append(
                    PersonServiceView(
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

    async def set_person_service(
        self,
        *,
        admin_id: uuid.UUID,
        owner_id: uuid.UUID,
        service: str,
        level: str,
        allowed: bool | None,
        note: str | None = None,
    ) -> None:
        """`allowed=None` removes the person's ruling, so they inherit the
        platform's again."""
        await self._person(owner_id)
        await ServiceAccessService(self.session, owner_id).set_person(
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
            target_type="user",
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
class PersonServiceView:
    service: str
    app: str
    name: str
    level: str
    allowed: bool
    overridden: bool
    note: str | None
