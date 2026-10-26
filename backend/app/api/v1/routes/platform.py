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
    full_name: str | None
    active: bool
    created_at: datetime


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


class ConnectionAccessRow(BaseModel):
    kind: str
    display_name: str
    platform_ready: bool
    allowed: bool
    overridden: bool
    note: str | None


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


class PersonDetail(BaseModel):
    """Counts and health. Never content."""

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    active: bool
    created_at: datetime
    task_count: int
    providers: list[ProviderStatusRow]


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


def _row(user: User) -> PersonRow:
    return PersonRow(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        active=user.is_active,
        created_at=user.created_at,
    )


@router.get("/people", response_model=list[PersonRow], summary="List accounts")
async def list_people(admin: AdminDep, session: SessionDep) -> list[PersonRow]:
    return [_row(user) for user in await PlatformService(session).list_people()]


@router.post("/people/{owner_id}/suspend", response_model=PersonRow, summary="Suspend")
async def suspend(owner_id: uuid.UUID, admin: AdminDep, session: SessionDep) -> PersonRow:
    """They cannot sign in. Nothing of theirs is read or deleted."""
    user = await PlatformService(session).set_active(
        admin_id=admin.id, owner_id=owner_id, active=False
    )
    await session.commit()
    return _row(user)


@router.post("/people/{owner_id}/restore", response_model=PersonRow, summary="Restore")
async def restore(owner_id: uuid.UUID, admin: AdminDep, session: SessionDep) -> PersonRow:
    user = await PlatformService(session).set_active(
        admin_id=admin.id, owner_id=owner_id, active=True
    )
    await session.commit()
    return _row(user)


@router.get("/audit", response_model=list[AuditEntry], summary="The diary")
async def audit_log(
    admin: AdminDep,
    session: SessionDep,
    limit: Annotated[int, Query(le=500)] = 100,
) -> list[AuditEntry]:
    """Every platform-admin action, newest first.

    Append-only at the database level: the application role has no
    UPDATE or DELETE on this table, so the log survives a compromise
    of the application itself.
    """
    rows = await session.execute(
        select(PlatformAdminAudit, PlatformAdmin.email)
        .outerjoin(PlatformAdmin, PlatformAdmin.id == PlatformAdminAudit.admin_id)
        .order_by(PlatformAdminAudit.created_at.desc())
        .limit(limit)
    )
    return [
        AuditEntry(
            id=entry.id,
            admin_email=email,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            detail=entry.detail,
            created_at=entry.created_at,
        )
        for entry, email in rows.all()
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

    return PersonDetail(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        active=user.is_active,
        created_at=user.created_at,
        task_count=tasks or 0,
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
    base_url: str | None
    api_format: str
    auth_header: str | None
    default_model: str | None
    docs_url: str | None
    trains_on_data: bool
    enabled: bool


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


def _provider_row(p: SupportedProvider) -> ProviderRow:
    return ProviderRow(
        key=p.key,
        display_name=p.display_name,
        base_url=p.base_url,
        api_format=p.api_format,
        auth_header=p.auth_header,
        default_model=p.default_model,
        docs_url=p.docs_url,
        trains_on_data=p.trains_on_data,
        enabled=p.enabled,
    )


@router.get("/providers", response_model=list[ProviderRow], summary="The AI provider catalog")
async def list_providers(admin: AdminDep, session: SessionDep) -> list[ProviderRow]:
    return [_provider_row(p) for p in await ProviderCatalog(session).all()]


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
    return _provider_row(row)


@router.patch("/providers/{key}", response_model=ProviderRow, summary="Pause or resume a provider")
async def set_provider_enabled(
    key: str, body: SetProviderEnabledRequest, admin: AdminDep, session: SessionDep
) -> ProviderRow:
    row = await ProviderCatalog(session).set_enabled(
        admin_id=admin.id, key=key, enabled=body.enabled
    )
    await session.commit()
    return _provider_row(row)
