"""Company (organization) routes.

Every path here is nested under `/orgs/{org_id}`, which is what makes
`get_context` resolve the company from the caller's memberships. A caller
who is not a member gets 404 before the handler body ever runs.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.v1.deps import ContextDep, RequestContext, SessionDep, require_permission
from app.core.permissions import Permission
from app.db.models.ai_employee import AIEmployee, EmployeeStatus
from app.db.models.identity import Role
from app.db.models.policy import Connection
from app.db.models.provider import ProviderConfig
from app.db.models.task import Task
from app.db.repositories.identity_repo import MembershipRepository
from app.schemas.auth import (
    InviteRequest,
    InviteResponse,
    MemberSummary,
    UpdateMemberRoleRequest,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/orgs/{org_id}", tags=["organizations"])

ManageMembers = Annotated[RequestContext, Depends(require_permission(Permission.MEMBER_MANAGE))]
ReadMembers = Annotated[RequestContext, Depends(require_permission(Permission.MEMBER_READ))]
ReadTasks = Annotated[RequestContext, Depends(require_permission(Permission.TASK_READ))]


class SetupStatus(BaseModel):
    """How far a company is through first-time setup.

    Counts only, so members may read it too: a member stuck because no
    AI key exists should see why, without seeing the key.
    """

    ai_connected: bool
    apps_connected: bool
    employees: int
    employees_active: int
    tasks: int


@router.get("/setup", summary="First-time setup progress")
async def setup_status(ctx: ReadTasks, session: SessionDep) -> SetupStatus:
    async def count(stmt: object) -> int:
        return int(await session.scalar(stmt) or 0)  # type: ignore[call-overload]

    org = ctx.org_id
    return SetupStatus(
        ai_connected=await count(
            select(func.count()).select_from(ProviderConfig).where(ProviderConfig.org_id == org)
        )
        > 0,
        apps_connected=await count(
            select(func.count())
            .select_from(Connection)
            .where(Connection.org_id == org, Connection.enabled.is_(True))
        )
        > 0,
        employees=await count(
            select(func.count()).select_from(AIEmployee).where(AIEmployee.org_id == org)
        ),
        employees_active=await count(
            select(func.count())
            .select_from(AIEmployee)
            .where(AIEmployee.org_id == org, AIEmployee.status == EmployeeStatus.ACTIVE)
        ),
        tasks=await count(select(func.count()).select_from(Task).where(Task.org_id == org)),
    )


@router.get("/members", response_model=list[MemberSummary], summary="List members")
async def list_members(ctx: ReadMembers, session: SessionDep) -> list[MemberSummary]:
    rows = await MembershipRepository(session).list_members(ctx.org_id)
    return [
        MemberSummary(id=user.id, email=user.email, full_name=user.full_name, role=role)
        for user, role in rows
    ]


@router.post(
    "/invites",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a teammate",
)
async def create_invite(
    body: InviteRequest,
    ctx: ManageMembers,
    session: SessionDep,
) -> InviteResponse:
    invitation, raw_token = await AuthService(session).create_invitation(
        org_id=ctx.org_id,
        email=body.email,
        role=body.role,
        invited_by=ctx.user_id,
    )
    # The raw token appears here and nowhere else, ever. There is no email
    # service, so the admin copies this and sends it themselves.
    return InviteResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        invite_token=raw_token,
        expires_at=invitation.expires_at,
    )


@router.patch(
    "/members/{user_id}",
    response_model=MemberSummary,
    summary="Change a member's role",
)
async def update_member_role(
    user_id: uuid.UUID,
    body: UpdateMemberRoleRequest,
    ctx: ManageMembers,
    session: SessionDep,
) -> MemberSummary:
    membership = await AuthService(session).change_member_role(
        org_id=ctx.org_id, target_user_id=user_id, new_role=body.role
    )
    await session.flush()

    rows = await MembershipRepository(session).list_members(ctx.org_id)
    user = next(u for u, _ in rows if u.id == user_id)
    return MemberSummary(
        id=user.id, email=user.email, full_name=user.full_name, role=membership.role
    )


@router.delete(
    "/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member",
)
async def remove_member(user_id: uuid.UUID, ctx: ManageMembers, session: SessionDep) -> None:
    await AuthService(session).remove_member(org_id=ctx.org_id, target_user_id=user_id)


@router.get("", response_model=dict, summary="Company details")
async def get_org(ctx: ContextDep, session: SessionDep) -> dict[str, object]:
    from app.db.repositories.identity_repo import OrganizationRepository

    org = await OrganizationRepository(session).get(ctx.org_id)
    if org is None:  # pragma: no cover - get_context already proved membership
        from app.core.errors import NotFoundError

        raise NotFoundError()

    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "status": org.status.value,
        "max_employees": org.max_employees,
        "your_role": Role(ctx.role).value,
    }
