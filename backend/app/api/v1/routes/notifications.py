"""Notification settings: where a company hears about its runs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.v1.deps import RequestContext, SessionDep, require_permission
from app.config import get_settings
from app.core.permissions import Permission
from app.db.models.notification import NotificationSettings
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/orgs/{org_id}", tags=["notifications"])

CanManage = Annotated[RequestContext, Depends(require_permission(Permission.ORG_MANAGE))]


class NotificationSettingsResponse(BaseModel):
    email_enabled: bool
    # False when the platform has no SMTP server: the toggle is shown
    # but explains why nothing will arrive.
    email_available: bool
    slack_enabled: bool
    slack_connected: bool
    slack_webhook_last4: str | None
    on_approval_requested: bool
    on_task_completed: bool
    on_task_failed: bool


class UpdateNotificationSettings(BaseModel):
    email_enabled: bool = True
    slack_enabled: bool = False
    on_approval_requested: bool = True
    on_task_completed: bool = True
    on_task_failed: bool = True
    # Write-only. Omit to keep the current webhook; send a new one to
    # replace it; set `clear_slack_webhook` to remove it.
    slack_webhook_url: str | None = Field(default=None, max_length=500)
    clear_slack_webhook: bool = False


class TestResult(BaseModel):
    email: str
    slack: str


def _response(row: NotificationSettings) -> NotificationSettingsResponse:
    return NotificationSettingsResponse(
        email_enabled=row.email_enabled,
        email_available=get_settings().email_notifications_available,
        slack_enabled=row.slack_enabled,
        slack_connected=row.slack_webhook_enc is not None,
        slack_webhook_last4=row.slack_webhook_last4,
        on_approval_requested=row.on_approval_requested,
        on_task_completed=row.on_task_completed,
        on_task_failed=row.on_task_failed,
    )


@router.get(
    "/notifications",
    response_model=NotificationSettingsResponse,
    summary="How we are notified",
)
async def get_settings_route(ctx: CanManage, session: SessionDep) -> NotificationSettingsResponse:
    return _response(await NotificationService(session, ctx.org_id).settings())


@router.put(
    "/notifications",
    response_model=NotificationSettingsResponse,
    summary="Change how we are notified",
)
async def update_settings(
    body: UpdateNotificationSettings, ctx: CanManage, session: SessionDep
) -> NotificationSettingsResponse:
    row = await NotificationService(session, ctx.org_id).update(**body.model_dump())
    return _response(row)


@router.post(
    "/notifications/test",
    response_model=TestResult,
    summary="Send a test message on every enabled channel",
)
async def send_test(ctx: CanManage, session: SessionDep) -> TestResult:
    result = await NotificationService(session, ctx.org_id).send_test(ctx.user)
    return TestResult(email=result.get("email", "off"), slack=result.get("slack", "off"))
