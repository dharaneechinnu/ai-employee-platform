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
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, EmailStr, Field

from app.api.v1.deps import SessionDep
from app.core.errors import AuthError
from app.core.security import decode_access_token
from app.db.models.identity import PlatformAdmin
from app.db.models.organization import OrgStatus
from app.db.repositories.identity_repo import PlatformAdminRepository
from app.services.platform_service import PlatformService

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
