"""Platform Admin routes.

Everything here lives under /platform and requires a platform token,
which is a different token type from a customer's. A customer access
token is rejected even if the caller is a Company Admin.

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
from app.db.models.ai_employee import COUNTS_TOWARD_LIMIT, AIEmployee
from app.db.models.identity import Membership, PlatformAdmin, PlatformAdminAudit
from app.db.models.organization import Organization, OrgStatus
from app.db.models.provider import ProviderConfig
from app.db.models.task import Task
from app.db.repositories.identity_repo import PlatformAdminRepository
from app.services.platform_service import OAuthAppView, PlatformService

router = APIRouter(prefix="/platform", tags=["platform admin"])


# ----------------------------------------------------------------- schemas


class PlatformLoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str = Field(min_length=6, max_length=6)


class PlatformTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth scheme name


class CreateCompanyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    first_admin_email: EmailStr
    max_employees: int = Field(default=3, ge=0, le=1000)


class CreateCompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    max_employees: int
    invite_token: str


class CompanyRow(BaseModel):
    """What the Platform Admin may see: counts and health, never content."""

    id: uuid.UUID
    name: str
    slug: str
    status: str
    max_employees: int
    employees_used: int
    member_count: int


class SetLimitRequest(BaseModel):
    max_employees: int = Field(ge=0, le=1000)


class AuditEntry(BaseModel):
    """One line of the diary.

    Records who did what to which company. It never holds customer
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


class SaveOAuthAppRequest(BaseModel):
    client_id: str = Field(min_length=5, max_length=300)
    # Write-only. No endpoint returns it, here or anywhere, so a
    # mistyped secret is replaced rather than corrected.
    client_secret: str = Field(min_length=5, max_length=500)


class SetOAuthAppEnabledRequest(BaseModel):
    enabled: bool


class ProviderStatusRow(BaseModel):
    """Whether a company has connected a provider. Nothing else.

    No key, not even masked, and no usage. A customer's API key is
    their money; being unable to read it is the point.
    """

    provider_key: str
    connected: bool
    status: str
    last_tested_at: datetime | None


class CompanyDetail(BaseModel):
    """Counts and health. Never content."""

    id: uuid.UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    max_employees: int
    employees_used: int
    member_count: int
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
    token = await PlatformService(session).login(
        email=body.email, password=body.password, totp_code=body.totp_code
    )
    return PlatformTokenResponse(access_token=token)


@router.post(
    "/companies",
    response_model=CreateCompanyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a company and its first invite",
)
async def create_company(
    body: CreateCompanyRequest, admin: AdminDep, session: SessionDep
) -> CreateCompanyResponse:
    org, raw_token = await PlatformService(session).create_company(
        admin_id=admin.id,
        name=body.name,
        slug=body.slug,
        first_admin_email=body.first_admin_email,
        max_employees=body.max_employees,
    )
    # The invite token appears here once. There is no email service, so
    # the Platform Admin copies this and sends it themselves.
    return CreateCompanyResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        max_employees=org.max_employees,
        invite_token=raw_token,
    )


@router.get("/companies", response_model=list[CompanyRow], summary="List companies")
async def list_companies(admin: AdminDep, session: SessionDep) -> list[CompanyRow]:
    stats = await PlatformService(session).list_companies()
    return [
        CompanyRow(
            id=s.org.id,
            name=s.org.name,
            slug=s.org.slug,
            status=s.org.status.value,
            max_employees=s.org.max_employees,
            employees_used=s.employee_count,
            member_count=s.member_count,
        )
        for s in stats
    ]


@router.patch(
    "/companies/{org_id}/limits", response_model=CompanyRow, summary="Change the employee limit"
)
async def set_limit(
    org_id: uuid.UUID, body: SetLimitRequest, admin: AdminDep, session: SessionDep
) -> CompanyRow:
    org = await PlatformService(session).set_employee_limit(
        admin_id=admin.id, org_id=org_id, max_employees=body.max_employees
    )
    return CompanyRow(
        id=org.id,
        name=org.name,
        slug=org.slug,
        status=org.status.value,
        max_employees=org.max_employees,
        employees_used=0,
        member_count=0,
    )


async def _set_status(
    org_id: uuid.UUID, admin: PlatformAdmin, session: SessionDep, status_: OrgStatus
) -> CompanyRow:
    org = await PlatformService(session).set_status(
        admin_id=admin.id, org_id=org_id, status=status_
    )
    return CompanyRow(
        id=org.id,
        name=org.name,
        slug=org.slug,
        status=org.status.value,
        max_employees=org.max_employees,
        employees_used=0,
        member_count=0,
    )


@router.post("/companies/{org_id}/suspend", response_model=CompanyRow, summary="Suspend")
async def suspend(org_id: uuid.UUID, admin: AdminDep, session: SessionDep) -> CompanyRow:
    return await _set_status(org_id, admin, session, OrgStatus.SUSPENDED)


@router.post("/companies/{org_id}/reactivate", response_model=CompanyRow, summary="Reactivate")
async def reactivate(org_id: uuid.UUID, admin: AdminDep, session: SessionDep) -> CompanyRow:
    return await _set_status(org_id, admin, session, OrgStatus.ACTIVE)


@router.post("/companies/{org_id}/close", response_model=CompanyRow, summary="Close")
async def close(org_id: uuid.UUID, admin: AdminDep, session: SessionDep) -> CompanyRow:
    return await _set_status(org_id, admin, session, OrgStatus.CLOSED)


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
    "/companies/{org_id}",
    response_model=CompanyDetail,
    summary="One company: counts and health only",
)
async def company_detail(org_id: uuid.UUID, admin: AdminDep, session: SessionDep) -> CompanyDetail:
    """Deliberately thin.

    There is no sibling endpoint that returns this company's tasks,
    memories, emails or credentials, so support work is done by asking
    the customer to share what they see. That trade is the whole point:
    "we technically cannot read your data" is a promise worth keeping.
    """
    org = await session.get(Organization, org_id)
    if org is None:
        raise NotFoundError("No such company.")

    members = await session.scalar(
        select(func.count()).select_from(Membership).where(Membership.org_id == org_id)
    )
    employees = await session.scalar(
        select(func.count())
        .select_from(AIEmployee)
        .where(AIEmployee.org_id == org_id, AIEmployee.status.in_(COUNTS_TOWARD_LIMIT))
    )
    tasks = await session.scalar(
        select(func.count()).select_from(Task).where(Task.org_id == org_id)
    )

    configs = (
        await session.scalars(select(ProviderConfig).where(ProviderConfig.org_id == org_id))
    ).all()

    return CompanyDetail(
        id=org.id,
        name=org.name,
        slug=org.slug,
        status=org.status.value,
        created_at=org.created_at,
        max_employees=org.max_employees,
        employees_used=employees or 0,
        member_count=members or 0,
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
    """What a company's Connections page depends on.

    Google and Microsoft issue one app registration per application,
    not per customer, so this is a platform-level setting: every
    company signs in through the same app and grants it access to
    their own mailbox. Until it is set here, the one-click buttons on
    every company's Connections page are disabled, and nothing inside
    the product could previously turn them on.
    """
    return [
        OAuthAppRow(**asdict(app)) for app in await PlatformService(session).oauth_apps()
    ]


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
