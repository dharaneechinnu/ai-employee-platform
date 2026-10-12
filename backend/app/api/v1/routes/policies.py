"""Permission policy and approval routes.

A company may set any action looser or stricter than the platform
default. The one exception is the catastrophic blocklist, which the
service refuses in the backend — not merely greys out on the screen,
since a screen-only check is bypassed by calling the API directly.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.agent.tools.registry import BLOCKED_ACTIONS, registry
from app.api.v1.deps import RequestContext, SessionDep, require_permission
from app.core.permissions import Permission
from app.db.models.policy import ApprovalStatus, PolicyScope, PolicySetting
from app.db.models.task import Run
from app.services.approval_service import ApprovalService
from app.services.policy_service import PolicyService
from app.workers.queue import enqueue_task

router = APIRouter(prefix="/orgs/{org_id}", tags=["policy and approvals"])

CanManagePolicy = Annotated[RequestContext, Depends(require_permission(Permission.POLICY_MANAGE))]
CanDecide = Annotated[RequestContext, Depends(require_permission(Permission.APPROVAL_DECIDE))]
CanRead = Annotated[RequestContext, Depends(require_permission(Permission.TASK_READ))]


class PolicyRowResponse(BaseModel):
    scope: PolicyScope
    scope_value: str
    side_effect: str | None
    setting: PolicySetting
    # False means this company changed it from the platform default.
    is_default: bool


class SetPolicyRequest(BaseModel):
    scope: PolicyScope
    scope_value: str = Field(min_length=1, max_length=100)
    side_effect: str | None = None
    setting: PolicySetting


class ToolCatalogueEntry(BaseModel):
    name: str
    pack: str
    description: str
    side_effect: str
    effective_setting: PolicySetting
    reason: str
    permanently_blocked: bool
    # The connection kind this tool needs, so the tool picker can say
    # "connect Google first" instead of letting it fail at run time.
    requires_connection: str | None = None


class ApprovalResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    tool_name: str
    side_effect: str
    # The whole proposed action. An approval screen that shows only a
    # summary is theatre: you cannot approve what you cannot read.
    proposed: dict[str, Any]
    status: ApprovalStatus
    expires_at: datetime
    created_at: datetime
    task_title: str | None = None


@router.get("/policies", response_model=list[PolicyRowResponse], summary="Effective policy")
async def get_policies(ctx: CanManagePolicy, session: SessionDep) -> list[PolicyRowResponse]:
    return [
        PolicyRowResponse(**asdict(row))
        for row in await PolicyService(session, ctx.org_id).effective()
    ]


@router.put("/policies", response_model=PolicyRowResponse, summary="Set one rule")
async def set_policy(
    body: SetPolicyRequest, ctx: CanManagePolicy, session: SessionDep
) -> PolicyRowResponse:
    policy = await PolicyService(session, ctx.org_id).set_rule(
        scope=body.scope,
        scope_value=body.scope_value,
        side_effect=body.side_effect,
        setting=body.setting,
        user_id=ctx.user_id,
    )
    return PolicyRowResponse(
        scope=policy.scope,
        scope_value=policy.scope_value,
        side_effect=policy.side_effect,
        setting=policy.setting,
        is_default=False,
    )


@router.post(
    "/policies/reset", status_code=status.HTTP_204_NO_CONTENT, summary="Back to the defaults"
)
async def reset_policies(ctx: CanManagePolicy, session: SessionDep) -> None:
    await PolicyService(session, ctx.org_id).reset()


@router.get(
    "/tools",
    response_model=list[ToolCatalogueEntry],
    summary="Every tool and what this company's policy says about it",
)
async def tool_catalogue(ctx: CanRead, session: SessionDep) -> list[ToolCatalogueEntry]:
    resolver = await PolicyService(session, ctx.org_id).resolver()
    entries = []

    for tool in registry.all():
        decision = resolver.evaluate(tool.name)
        entries.append(
            ToolCatalogueEntry(
                name=tool.name,
                pack=tool.pack,
                description=tool.description,
                side_effect=tool.side_effect.value,
                effective_setting=decision.setting,
                reason=decision.reason,
                permanently_blocked=tool.name in BLOCKED_ACTIONS,
                requires_connection=tool.requires_connection,
            )
        )
    return entries


@router.get("/approvals", response_model=list[ApprovalResponse], summary="Pending approvals")
async def list_approvals(ctx: CanDecide, session: SessionDep) -> list[ApprovalResponse]:
    return [
        ApprovalResponse(
            id=p.approval.id,
            run_id=p.approval.run_id,
            tool_name=p.approval.tool_name,
            side_effect=p.approval.side_effect,
            proposed=p.approval.proposed,
            status=p.approval.status,
            expires_at=p.approval.expires_at,
            created_at=p.approval.created_at,
            task_title=p.task_title,
        )
        for p in await ApprovalService(session, ctx.org_id).list_pending()
    ]


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse, summary="Read one")
async def get_approval(
    approval_id: uuid.UUID, ctx: CanDecide, session: SessionDep
) -> ApprovalResponse:
    a = await ApprovalService(session, ctx.org_id).get(approval_id)
    return ApprovalResponse(
        id=a.id,
        run_id=a.run_id,
        tool_name=a.tool_name,
        side_effect=a.side_effect,
        proposed=a.proposed,
        status=a.status,
        expires_at=a.expires_at,
        created_at=a.created_at,
    )


async def _decide(
    approval_id: uuid.UUID, ctx: RequestContext, session: SessionDep, approve: bool
) -> ApprovalResponse:
    service = ApprovalService(session, ctx.org_id)
    a = await service.decide(approval_id=approval_id, approve=approve, user_id=ctx.user_id)
    await session.commit()

    if approve:
        # Put the run back on the queue. A worker reloads the saved
        # conversation and carries on from the step that paused, which
        # is why the state lives in Postgres rather than in the process.
        run = await session.get(Run, a.run_id)
        if run is not None:
            await enqueue_task(run.task_id)

    return ApprovalResponse(
        id=a.id,
        run_id=a.run_id,
        tool_name=a.tool_name,
        side_effect=a.side_effect,
        proposed=a.proposed,
        status=a.status,
        expires_at=a.expires_at,
        created_at=a.created_at,
    )


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse, summary="Approve")
async def approve(approval_id: uuid.UUID, ctx: CanDecide, session: SessionDep) -> ApprovalResponse:
    return await _decide(approval_id, ctx, session, approve=True)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse, summary="Reject")
async def reject(approval_id: uuid.UUID, ctx: CanDecide, session: SessionDep) -> ApprovalResponse:
    return await _decide(approval_id, ctx, session, approve=False)
