"""Platform Admin routes.

Everything here lives under /platform and requires a platform token,
which is a different token type from a customer's. A customer access
token is rejected, whoever it belongs to.

Note what is absent: no endpoint returns task text, memory, credentials
or any other customer content. That is the control — not an access
check that could be misconfigured, but an endpoint that does not exist.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.api.v1.deps import SessionDep
from app.core.errors import AuthError, NotFoundError
from app.core.security import decode_access_token
from app.db.models.identity import PlatformAdmin, PlatformAdminAudit, User
from app.db.models.provider import ProviderConfig, SupportedProvider
from app.db.models.task import Task
from app.db.repositories.identity_repo import PlatformAdminRepository
from app.services.platform_service import (
    OAuthAppView,
    PersonFacts,
    PlatformService,
)
from app.services.provider_catalog import ProviderCatalog

router = APIRouter(prefix="/platform", tags=["platform admin"])


# ----------------------------------------------------------------- schemas


class PlatformLoginRequest(BaseModel):
    email: EmailStr
    password: str


class PlatformTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth scheme name


class CreatePersonRequest(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=200)


class CreatePersonResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    # Shown once, right after creation. Only its hash is stored, so a
    # lost link means issuing another rather than looking one up.
    setup_token: str


class PersonRow(BaseModel):
    """What the Platform Admin may see: counts and health, never content."""

    id: uuid.UUID
    email: EmailStr
    username: str
    full_name: str | None
    active: bool
    created_at: datetime
    # "self" for a sign-up at /register, "invited" for an account staff made.
    joined_via: str = "self"
    # For an invited account: "waiting", "used" or "expired". None otherwise.
    setup_link: str | None = None
    setup_link_expires_at: datetime | None = None
    # The later of their last sign-in and their last session renewal.
    # None means they have never signed in.
    last_active_at: datetime | None = None


class SuspendRequest(BaseModel):
    # Staff's own words, kept in the audit entry. Optional.
    reason: str | None = Field(default=None, max_length=500)


class SetupLinkResponse(BaseModel):
    # Shown once, like the first one. Only its hash is stored.
    setup_token: str
    expires_at: datetime


class StaffMe(BaseModel):
    """Who is signed in to the staff console, for the strip at the top."""

    id: uuid.UUID
    email: str


class OverviewResponse(BaseModel):
    """The headline numbers. Counts only, never content."""

    people_total: int
    people_active: int
    people_suspended: int
    joined_this_week_self: int
    joined_this_week_invited: int
    setup_links_waiting: int
    setup_links_expiring_soon: int
    ai_keys_total: int
    ai_keys_free: int
    ai_keys_paid: int
    agents_built: int
    runs_this_week: int


class AppAccessRow(BaseModel):
    """One kind of app, for everyone, with how many people use it."""

    kind: str
    display_name: str
    platform_ready: bool
    allowed: bool
    people_connected: int
    people_with_own_settings: int


class SetAppAccessRequest(BaseModel):
    allowed: bool


class AuditEntry(BaseModel):
    """One line of the diary.

    Records who did what to which account. It never holds customer
    content, because no platform-admin action can read any.
    """

    id: uuid.UUID
    admin_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    # Who the target is, in words: a person's name (or email) for an
    # account, so the log reads "suspended Meera Iyer" and not a UUID.
    target_label: str | None = None
    detail: str | None
    created_at: datetime


class OAuthAppRow(BaseModel):
    """One one-click provider, registered or not."""

    provider: str
    display_name: str
    client_id: str | None
    secret_last4: str | None
    enabled: bool
    configured: bool
    redirect_uri: str
    docs_url: str
    from_environment: bool
    # When it was last saved here, and by which staff member.
    updated_at: datetime | None = None
    updated_by_email: str | None = None


class ConnectionAccessRow(BaseModel):
    kind: str
    display_name: str
    platform_ready: bool
    allowed: bool
    overridden: bool
    note: str | None
    # What everyone gets, for "Same as everyone".
    everyone_allowed: bool = True


class SetConnectionAccessRequest(BaseModel):
    # None clears the ruling and returns the person to the platform
    # default, which is not the same as allowing it outright.
    allowed: bool | None = None
    note: str | None = Field(default=None, max_length=300)


class SaveOAuthAppRequest(BaseModel):
    client_id: str = Field(min_length=5, max_length=300)
    # Write-only. No endpoint returns it, here or anywhere, so a
    # mistyped secret is replaced rather than corrected.
    client_secret: str = Field(min_length=5, max_length=500)


class SetOAuthAppEnabledRequest(BaseModel):
    enabled: bool


class ProviderStatusRow(BaseModel):
    """Whether a person has connected a provider. Nothing else.

    No key, not even masked, and no usage. A customer's API key is
    their money; being unable to read it is the point.
    """

    provider_key: str
    connected: bool
    status: str
    last_tested_at: datetime | None


class AppConnectedRow(BaseModel):
    """Whether a person has connected one kind of app. Yes or no only."""

    kind: str
    display_name: str
    connected: bool


class PersonDetail(PersonRow):
    """Counts and health. Never content."""

    task_count: int
    agent_count: int = 0
    scheduled_agent_count: int = 0
    runs_this_week: int = 0
    providers: list[ProviderStatusRow]
    apps: list[AppConnectedRow] = []


# ----------------------------------------------------------------- auth dep


async def get_platform_admin(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> PlatformAdmin:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError()

    try:
        payload = decode_access_token(
            authorization.split(" ", 1)[1].strip(), expected_type="platform_access"
        )
        admin_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        # A customer token lands here: its "typ" claim is "access", not
        # "platform_access", so it cannot be used to reach these routes.
        raise AuthError() from exc

    admin = await PlatformAdminRepository(session).get(admin_id)
    if admin is None or not admin.is_active:
        raise AuthError()
    return admin


AdminDep = Annotated[PlatformAdmin, Depends(get_platform_admin)]


# ----------------------------------------------------------------- routes


@router.post("/auth/login", response_model=PlatformTokenResponse, summary="Admin sign in")
async def platform_login(body: PlatformLoginRequest, session: SessionDep) -> PlatformTokenResponse:
    token = await PlatformService(session).login(email=body.email, password=body.password)
    return PlatformTokenResponse(access_token=token)


@router.post(
    "/people",
    response_model=CreatePersonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and its setup link",
)
async def create_person(
    body: CreatePersonRequest, admin: AdminDep, session: SessionDep
) -> CreatePersonResponse:
    user, raw_token = await PlatformService(session).create_person(
        admin_id=admin.id,
        email=body.email,
        full_name=body.full_name,
    )
    await session.commit()
    # Shown here once. There is no email service, so the Platform
    # Admin copies the link and sends it themselves. The person sets
    # their own password through it, so staff never know it.
    return CreatePersonResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        setup_token=raw_token,
    )


def _row(user: User, facts: PersonFacts | None = None) -> PersonRow:
    facts = facts or PersonFacts()
    return PersonRow(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        active=user.is_active,
        created_at=user.created_at,
        joined_via=facts.joined_via,
        setup_link=facts.setup_link,
        setup_link_expires_at=facts.setup_link_expires_at,
        last_active_at=facts.last_active_at,
    )


async def _one_row(service: PlatformService, user: User) -> PersonRow:
    return _row(user, (await service.people_facts([user.id])).get(user.id))


@router.get("/me", response_model=StaffMe, summary="Who is signed in")
async def staff_me(admin: AdminDep) -> StaffMe:
    return StaffMe(id=admin.id, email=admin.email)


@router.get("/overview", response_model=OverviewResponse, summary="The headline numbers")
async def overview(admin: AdminDep, session: SessionDep) -> OverviewResponse:
    """How many, never what: people, sign-ups, keys, agents and runs."""
    return OverviewResponse(**asdict(await PlatformService(session).overview()))


@router.get("/people", response_model=list[PersonRow], summary="List accounts")
async def list_people(admin: AdminDep, session: SessionDep) -> list[PersonRow]:
    service = PlatformService(session)
    facts = await service.people_facts()
    return [_row(user, facts.get(user.id)) for user in await service.list_people()]


@router.post("/people/{owner_id}/suspend", response_model=PersonRow, summary="Suspend")
async def suspend(
    owner_id: uuid.UUID,
    admin: AdminDep,
    session: SessionDep,
    body: SuspendRequest | None = None,
) -> PersonRow:
    """They cannot sign in. Nothing of theirs is read or deleted."""
    service = PlatformService(session)
    user = await service.set_active(
        admin_id=admin.id,
        owner_id=owner_id,
        active=False,
        reason=body.reason if body else None,
    )
    await session.commit()
    return await _one_row(service, user)


@router.post("/people/{owner_id}/restore", response_model=PersonRow, summary="Restore")
async def restore(owner_id: uuid.UUID, admin: AdminDep, session: SessionDep) -> PersonRow:
    service = PlatformService(session)
    user = await service.set_active(admin_id=admin.id, owner_id=owner_id, active=True)
    await session.commit()
    return await _one_row(service, user)


@router.post(
    "/people/{owner_id}/setup-link",
    response_model=SetupLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="A new setup link for an invited account",
)
async def reissue_setup_link(
    owner_id: uuid.UUID, admin: AdminDep, session: SessionDep
) -> SetupLinkResponse:
    """Ends the old link and makes a new one, shown once.

    Refused once the person has set a password, so staff can never use
    a link to get into a live account.
    """
    service = PlatformService(session)
    raw_token = await service.reissue_setup_link(admin_id=admin.id, owner_id=owner_id)
    await session.commit()
    facts = (await service.people_facts([owner_id]))[owner_id]
    assert facts.setup_link_expires_at is not None
    return SetupLinkResponse(setup_token=raw_token, expires_at=facts.setup_link_expires_at)


@router.get("/audit", response_model=list[AuditEntry], summary="The diary")
async def audit_log(
    admin: AdminDep,
    session: SessionDep,
    limit: Annotated[int, Query(le=500)] = 100,
    target_id: Annotated[str | None, Query(max_length=100)] = None,
    before: datetime | None = None,
) -> list[AuditEntry]:
    """Every platform-admin action, newest first.

    `target_id` narrows it to one account (or one app); `before` pages
    back through older entries.

    Append-only at the database level: the application role has no
    UPDATE or DELETE on this table, so the log survives a compromise
    of the application itself.
    """
    query = (
        select(PlatformAdminAudit, PlatformAdmin.email)
        .outerjoin(PlatformAdmin, PlatformAdmin.id == PlatformAdminAudit.admin_id)
        .order_by(PlatformAdminAudit.created_at.desc())
        .limit(limit)
    )
    if target_id is not None:
        query = query.where(PlatformAdminAudit.target_id == target_id)
    if before is not None:
        query = query.where(PlatformAdminAudit.created_at < before)
    rows = (await session.execute(query)).all()

    # Names for the accounts these entries are about. Name and email
    # are what staff already see in the people list; nothing more.
    people_ids = []
    for entry, _ in rows:
        if entry.target_type in ("user", "organization") and entry.target_id:
            try:
                people_ids.append(uuid.UUID(entry.target_id))
            except ValueError:
                continue
    names = {
        str(uid): full_name or email
        for uid, full_name, email in (
            await session.execute(
                select(User.id, User.full_name, User.email).where(User.id.in_(people_ids))
            )
        ).all()
    }
    return [
        AuditEntry(
            id=entry.id,
            admin_email=email,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            target_label=names.get(entry.target_id or ""),
            detail=entry.detail,
            created_at=entry.created_at,
        )
        for entry, email in rows
    ]


@router.get(
    "/people/{owner_id}",
    response_model=PersonDetail,
    summary="One person: counts and health only",
)
async def person_detail(owner_id: uuid.UUID, admin: AdminDep, session: SessionDep) -> PersonDetail:
    """Deliberately thin.

    There is no sibling endpoint that returns this person's tasks,
    memories, emails or credentials, so support work is done by asking
    the customer to share what they see. That trade is the whole point:
    "we technically cannot read your data" is a promise worth keeping.
    """
    user = await session.get(User, owner_id)
    if user is None:
        raise NotFoundError("No such account.")

    tasks = await session.scalar(
        select(func.count()).select_from(Task).where(Task.owner_id == owner_id)
    )

    configs = (
        await session.scalars(select(ProviderConfig).where(ProviderConfig.owner_id == owner_id))
    ).all()

    service = PlatformService(session)
    counts = await service.person_counts(owner_id)
    from app.services.connection_service import CATALOGUE

    names = {kind.value: str(meta["display_name"]) for kind, meta in CATALOGUE.items()}
    return PersonDetail(
        **(await _one_row(service, user)).model_dump(),
        task_count=tasks or 0,
        agent_count=counts.agent_count,
        scheduled_agent_count=counts.scheduled_agent_count,
        runs_this_week=counts.runs_this_week,
        apps=[
            AppConnectedRow(kind=kind, display_name=names[kind], connected=connected)
            for kind, connected in (counts.apps or {}).items()
        ],
        providers=[
            ProviderStatusRow(
                provider_key=c.provider_key,
                connected=True,
                status=c.status.value,
                last_tested_at=c.last_tested_at,
            )
            for c in configs
        ],
    )


# ------------------------------------------------- one-click sign-in


@router.get(
    "/oauth-apps",
    response_model=list[OAuthAppRow],
    summary="The Google and Microsoft apps behind one-click",
)
async def list_oauth_apps(admin: AdminDep, session: SessionDep) -> list[OAuthAppRow]:
    """What everyone's Connections page depends on.

    Google and Microsoft issue one app registration per application,
    not per customer, so this is a platform-level setting: every
    person signs in through the same app and grants it access to
    their own mailbox. Until it is set here, the one-click buttons on
    everyone's Connections page are disabled, and nothing inside
    the product could previously turn them on.
    """
    return [OAuthAppRow(**asdict(app)) for app in await PlatformService(session).oauth_apps()]


@router.put(
    "/oauth-apps/{provider_key}",
    response_model=OAuthAppRow,
    summary="Register or replace an app",
)
async def save_oauth_app(
    provider_key: str,
    body: SaveOAuthAppRequest,
    admin: AdminDep,
    session: SessionDep,
) -> OAuthAppRow:
    service = PlatformService(session)
    await service.save_oauth_app(
        admin_id=admin.id,
        provider_key=provider_key,
        client_id=body.client_id,
        client_secret=body.client_secret,
    )
    await session.commit()
    return _one(await service.oauth_apps(), provider_key)


@router.patch(
    "/oauth-apps/{provider_key}",
    response_model=OAuthAppRow,
    summary="Pause or resume an app",
)
async def set_oauth_app_enabled(
    provider_key: str,
    body: SetOAuthAppEnabledRequest,
    admin: AdminDep,
    session: SessionDep,
) -> OAuthAppRow:
    service = PlatformService(session)
    await service.set_oauth_app_enabled(
        admin_id=admin.id, provider_key=provider_key, enabled=body.enabled
    )
    await session.commit()
    return _one(await service.oauth_apps(), provider_key)


@router.delete(
    "/oauth-apps/{provider_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an app",
)
async def delete_oauth_app(provider_key: str, admin: AdminDep, session: SessionDep) -> None:
    service = PlatformService(session)
    await service.delete_oauth_app(admin_id=admin.id, provider_key=provider_key)
    await session.commit()


def _one(apps: list[OAuthAppView], provider_key: str) -> OAuthAppRow:
    for app in apps:
        if app.provider == provider_key:
            return OAuthAppRow(**asdict(app))
    raise NotFoundError(f"No such provider: '{provider_key}'.")


@router.get(
    "/people/{owner_id}/connections",
    response_model=list[ConnectionAccessRow],
    summary="Which connections this person may use",
)
async def person_connection_access(
    owner_id: uuid.UUID, admin: AdminDep, session: SessionDep
) -> list[ConnectionAccessRow]:
    """Still counts and settings, never content.

    This says whether Gmail is available to this person. It says
    nothing about what is in anyone's inbox, and there is no endpoint
    here that would.
    """
    if await session.get(User, owner_id) is None:
        raise NotFoundError("No such account.")
    return [
        ConnectionAccessRow(**asdict(row))
        for row in await PlatformService(session).connection_access(owner_id)
    ]


@router.put(
    "/people/{owner_id}/connections/{kind}",
    response_model=list[ConnectionAccessRow],
    summary="Open or close one connection for one person",
)
async def set_person_connection_access(
    owner_id: uuid.UUID,
    kind: str,
    body: SetConnectionAccessRequest,
    admin: AdminDep,
    session: SessionDep,
) -> list[ConnectionAccessRow]:
    service = PlatformService(session)
    await service.set_connection_access(
        admin_id=admin.id,
        owner_id=owner_id,
        kind=kind,
        allowed=body.allowed,
        note=body.note,
    )
    await session.commit()
    return [ConnectionAccessRow(**asdict(row)) for row in await service.connection_access(owner_id)]


@router.get(
    "/app-access",
    response_model=list[AppAccessRow],
    summary="Which kinds of app everyone may connect",
)
async def app_access(admin: AdminDep, session: SessionDep) -> list[AppAccessRow]:
    """One row per kind of app, with how many people have connected it.
    A count, never which account or what is in it."""
    return [AppAccessRow(**asdict(r)) for r in await PlatformService(session).app_access()]


@router.put(
    "/app-access/{kind}",
    response_model=list[AppAccessRow],
    summary="Open or close one kind of app for everyone",
)
async def set_app_access(
    kind: str, body: SetAppAccessRequest, admin: AdminDep, session: SessionDep
) -> list[AppAccessRow]:
    service = PlatformService(session)
    await service.set_app_access(admin_id=admin.id, kind=kind, allowed=body.allowed)
    await session.commit()
    return [AppAccessRow(**asdict(r)) for r in await service.app_access()]


# ------------------------------------------- which parts of an app, read or edit


class ServiceAccessRow(BaseModel):
    service: str
    app: str
    name: str
    level: str  # "read" or "edit"
    allowed: bool


class PersonServiceRow(ServiceAccessRow):
    # True when this person has their own ruling rather than inheriting.
    overridden: bool
    note: str | None


class SetServiceAccessRequest(BaseModel):
    allowed: bool


class SetPersonServiceRequest(BaseModel):
    # None removes the person's ruling so it inherits the platform's.
    allowed: bool | None = None
    note: str | None = Field(default=None, max_length=300)


@router.get(
    "/service-access",
    response_model=list[ServiceAccessRow],
    summary="What the platform allows for each part of each app",
)
async def service_access(admin: AdminDep, session: SessionDep) -> list[ServiceAccessRow]:
    return [ServiceAccessRow(**asdict(r)) for r in await PlatformService(session).service_matrix()]


@router.put(
    "/service-access/{service}/{level}",
    response_model=list[ServiceAccessRow],
    summary="Allow or block one part of an app, for everyone",
)
async def set_service_access(
    service: str,
    level: str,
    body: SetServiceAccessRequest,
    admin: AdminDep,
    session: SessionDep,
) -> list[ServiceAccessRow]:
    platform = PlatformService(session)
    await platform.set_platform_service(
        admin_id=admin.id, service=service, level=level, allowed=body.allowed
    )
    await session.commit()
    return [ServiceAccessRow(**asdict(r)) for r in await platform.service_matrix()]


@router.get(
    "/people/{owner_id}/services",
    response_model=list[PersonServiceRow],
    summary="Which parts of each app this person may use",
)
async def person_services(
    owner_id: uuid.UUID, admin: AdminDep, session: SessionDep
) -> list[PersonServiceRow]:
    return [
        PersonServiceRow(**asdict(r))
        for r in await PlatformService(session).person_services(owner_id)
    ]


@router.put(
    "/people/{owner_id}/services/{service}/{level}",
    response_model=list[PersonServiceRow],
    summary="Allow or block one part of an app for one person",
)
async def set_person_service(
    owner_id: uuid.UUID,
    service: str,
    level: str,
    body: SetPersonServiceRequest,
    admin: AdminDep,
    session: SessionDep,
) -> list[PersonServiceRow]:
    platform = PlatformService(session)
    await platform.set_person_service(
        admin_id=admin.id,
        owner_id=owner_id,
        service=service,
        level=level,
        allowed=body.allowed,
        note=body.note,
    )
    await session.commit()
    return [PersonServiceRow(**asdict(r)) for r in await platform.person_services(owner_id)]


# --------------------------------------------------- the AI provider catalog


class ProviderRow(BaseModel):
    key: str
    display_name: str
    # "llm" for an AI to run work on, "search" for a web search service.
    kind: str = "llm"
    base_url: str | None
    api_format: str
    auth_header: str | None
    default_model: str | None
    docs_url: str | None
    trains_on_data: bool
    enabled: bool
    free_tier: bool = False
    is_local: bool = False
    # How many people have saved a key for it. A count, never the keys.
    people_connected: int = 0
    # When it was last paused, and by whom, while it is paused.
    paused_at: datetime | None = None
    paused_by_email: str | None = None


class SaveProviderRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=8, max_length=500)
    # "openai" is what most providers speak; "anthropic" and "gemini" are their own formats.
    api_format: str = Field(default="openai", max_length=20)
    # Only for a provider that wants the key under its own header too.
    auth_header: str | None = Field(default=None, max_length=60)
    default_model: str | None = Field(default=None, max_length=100)
    docs_url: str | None = Field(default=None, max_length=500)
    trains_on_data: bool = False


class SetProviderEnabledRequest(BaseModel):
    enabled: bool


def _provider_row(
    p: SupportedProvider,
    people: int = 0,
    paused: tuple[datetime, str | None] | None = None,
) -> ProviderRow:
    return ProviderRow(
        key=p.key,
        display_name=p.display_name,
        kind=p.kind.value,
        base_url=p.base_url,
        api_format=p.api_format,
        auth_header=p.auth_header,
        default_model=p.default_model,
        docs_url=p.docs_url,
        trains_on_data=p.trains_on_data,
        enabled=p.enabled,
        free_tier=p.free_tier,
        is_local=p.is_local,
        people_connected=people,
        paused_at=paused[0] if paused and not p.enabled else None,
        paused_by_email=paused[1] if paused and not p.enabled else None,
    )


async def _last_paused(session: SessionDep) -> dict[str, tuple[datetime, str | None]]:
    """When each provider was last paused, and by whom, from the audit log."""
    rows = await session.execute(
        select(PlatformAdminAudit.target_id, PlatformAdminAudit.created_at, PlatformAdmin.email)
        .outerjoin(PlatformAdmin, PlatformAdmin.id == PlatformAdminAudit.admin_id)
        .where(
            PlatformAdminAudit.action == "provider_paused",
            PlatformAdminAudit.target_type == "provider",
        )
        .order_by(PlatformAdminAudit.created_at)
    )
    return {key: (at, email) for key, at, email in rows.all() if key}


async def _full_provider_row(session: SessionDep, row: SupportedProvider) -> ProviderRow:
    people = await PlatformService(session).people_per_provider()
    return _provider_row(row, people.get(row.key, 0), (await _last_paused(session)).get(row.key))


@router.get("/providers", response_model=list[ProviderRow], summary="The AI provider catalog")
async def list_providers(admin: AdminDep, session: SessionDep) -> list[ProviderRow]:
    people = await PlatformService(session).people_per_provider()
    paused = await _last_paused(session)
    return [
        _provider_row(p, people.get(p.key, 0), paused.get(p.key))
        for p in await ProviderCatalog(session).all()
    ]


@router.put(
    "/providers/{key}",
    response_model=ProviderRow,
    summary="Add a provider, or change one, without a release",
)
async def save_provider(
    key: str, body: SaveProviderRequest, admin: AdminDep, session: SessionDep
) -> ProviderRow:
    row = await ProviderCatalog(session).save(admin_id=admin.id, key=key, **body.model_dump())
    await session.commit()
    return await _full_provider_row(session, row)


@router.patch("/providers/{key}", response_model=ProviderRow, summary="Pause or resume a provider")
async def set_provider_enabled(
    key: str, body: SetProviderEnabledRequest, admin: AdminDep, session: SessionDep
) -> ProviderRow:
    row = await ProviderCatalog(session).set_enabled(
        admin_id=admin.id, key=key, enabled=body.enabled
    )
    await session.commit()
    return await _full_provider_row(session, row)
