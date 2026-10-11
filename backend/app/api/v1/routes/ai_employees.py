"""AI Employee routes.

Admin builds, Member uses: reads need EMPLOYEE_READ, writes need
EMPLOYEE_WRITE, which only an admin holds.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.v1.deps import RequestContext, SessionDep, require_permission
from app.core.permissions import Permission
from app.db.models.ai_employee import EmployeeStatus
from app.schemas.ai_employee import (
    CreateEmployeeRequest,
    CreateTemplateRequest,
    EmployeeConfig,
    EmployeeListItem,
    EmployeeListResponse,
    EmployeeResponse,
    PromptPreviewResponse,
    TemplateResponse,
    UpdateEmployeeRequest,
    VersionSummary,
)
from app.services.employee_service import EmployeeService, build_system_prompt

router = APIRouter(prefix="/orgs/{org_id}", tags=["ai employees"])

CanRead = Annotated[RequestContext, Depends(require_permission(Permission.EMPLOYEE_READ))]
CanWrite = Annotated[RequestContext, Depends(require_permission(Permission.EMPLOYEE_WRITE))]


def _service(ctx: RequestContext, session: SessionDep) -> EmployeeService:
    return EmployeeService(session, ctx.org_id)


def _to_response(employee, version) -> EmployeeResponse:  # type: ignore[no-untyped-def]
    return EmployeeResponse(
        id=employee.id,
        name=employee.name,
        job_title=employee.job_title,
        department=employee.department,
        avatar=employee.avatar,
        status=employee.status,
        version_no=version.version_no,
        config=EmployeeConfig.model_validate(version.config),
        created_at=employee.created_at,
    )


@router.get("/ai-employees", response_model=EmployeeListResponse, summary="List AI Employees")
async def list_employees(ctx: CanRead, session: SessionDep) -> EmployeeListResponse:
    service = _service(ctx, session)
    employees = await service.list_employees()
    return EmployeeListResponse(
        items=[EmployeeListItem.model_validate(e) for e in employees],
        used=await service.count_live(),
        limit=await service.limit(),
    )


@router.post(
    "/ai-employees",
    response_model=EmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an AI Employee",
)
async def create_employee(
    body: CreateEmployeeRequest, ctx: CanWrite, session: SessionDep
) -> EmployeeResponse:
    service = _service(ctx, session)

    config = body.config
    if body.template_id is not None:
        template = await service.get_template(body.template_id)
        # Template fills the gaps; anything the caller set wins.
        merged = {**template.config, **config.model_dump(mode="json", exclude_defaults=True)}
        config = EmployeeConfig.model_validate(merged)

    result = await service.create(
        name=body.name,
        job_title=body.job_title,
        department=body.department,
        avatar=body.avatar,
        config=config,
        created_by=ctx.user_id,
    )
    return _to_response(result.employee, result.version)


@router.get("/ai-employees/{employee_id}", response_model=EmployeeResponse, summary="Read one")
async def get_employee(
    employee_id: uuid.UUID, ctx: CanRead, session: SessionDep
) -> EmployeeResponse:
    result = await _service(ctx, session).get(employee_id)
    return _to_response(result.employee, result.version)


@router.patch(
    "/ai-employees/{employee_id}",
    response_model=EmployeeResponse,
    summary="Edit (creates a new version)",
)
async def update_employee(
    employee_id: uuid.UUID,
    body: UpdateEmployeeRequest,
    ctx: CanWrite,
    session: SessionDep,
) -> EmployeeResponse:
    result = await _service(ctx, session).update(
        employee_id,
        name=body.name,
        job_title=body.job_title,
        department=body.department,
        avatar=body.avatar,
        config=body.config,
        updated_by=ctx.user_id,
    )
    return _to_response(result.employee, result.version)


@router.delete(
    "/ai-employees/{employee_id}",
    response_model=EmployeeResponse,
    summary="Archive (frees a slot, keeps the history)",
)
async def archive_employee(
    employee_id: uuid.UUID, ctx: CanWrite, session: SessionDep
) -> EmployeeResponse:
    result = await _service(ctx, session).set_status(employee_id, EmployeeStatus.ARCHIVED)
    return _to_response(result.employee, result.version)


@router.post(
    "/ai-employees/{employee_id}/activate", response_model=EmployeeResponse, summary="Activate"
)
async def activate(employee_id: uuid.UUID, ctx: CanWrite, session: SessionDep) -> EmployeeResponse:
    result = await _service(ctx, session).set_status(employee_id, EmployeeStatus.ACTIVE)
    return _to_response(result.employee, result.version)


@router.post("/ai-employees/{employee_id}/pause", response_model=EmployeeResponse, summary="Pause")
async def pause(employee_id: uuid.UUID, ctx: CanWrite, session: SessionDep) -> EmployeeResponse:
    result = await _service(ctx, session).set_status(employee_id, EmployeeStatus.PAUSED)
    return _to_response(result.employee, result.version)


@router.get(
    "/ai-employees/{employee_id}/versions",
    response_model=list[VersionSummary],
    summary="Version history",
)
async def list_versions(
    employee_id: uuid.UUID, ctx: CanRead, session: SessionDep
) -> list[VersionSummary]:
    versions = await _service(ctx, session).list_versions(employee_id)
    return [VersionSummary.model_validate(v) for v in versions]


@router.post(
    "/ai-employees/{employee_id}/preview-prompt",
    response_model=PromptPreviewResponse,
    summary="See the exact text the model will receive",
)
async def preview_prompt(
    employee_id: uuid.UUID, ctx: CanRead, session: SessionDep
) -> PromptPreviewResponse:
    result = await _service(ctx, session).get(employee_id)
    prompt = build_system_prompt(
        EmployeeConfig.model_validate(result.version.config),
        name=result.employee.name,
        job_title=result.employee.job_title,
    )
    return PromptPreviewResponse(system_prompt=prompt, character_count=len(prompt))


# ----------------------------------------------------------------- templates


@router.get("/templates", response_model=list[TemplateResponse], summary="List templates")
async def list_templates(ctx: CanRead, session: SessionDep) -> list[TemplateResponse]:
    templates = await _service(ctx, session).list_templates()
    return [
        TemplateResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            department=t.department,
            config=t.config,
            is_platform_template=t.org_id is None,
        )
        for t in templates
    ]


@router.post(
    "/templates",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save an AI Employee as a reusable template",
)
async def create_template(
    body: CreateTemplateRequest, ctx: CanWrite, session: SessionDep
) -> TemplateResponse:
    template = await _service(ctx, session).save_as_template(
        employee_id=body.employee_id, name=body.name, description=body.description
    )
    return TemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        department=template.department,
        config=template.config,
        is_platform_template=False,
    )
