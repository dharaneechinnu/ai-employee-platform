"""Notification settings: where a company hears about its runs."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.v1.deps import ContextDep, SessionDep
from app.config import get_settings
from app.db.models.notification import NotificationSettings
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/me", tags=["notifications"])


class NotificationSettingsResponse(BaseModel):
    email_enabled: bool
    # False when the platform has no SMTP server: the toggle is shown
    # but explains why nothing will arrive.
    email_available: bool
    slack_enabled: bool
    slack_connected: bool
    slack_webhook_last4: str | None
    on_approval_requested: bool


class UpdateNotificationSettings(BaseModel):
    email_enabled: bool = True
    slack_enabled: bool = False
    on_approval_requested: bool = True
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
    )


@router.get(
    "/notifications",
    response_model=NotificationSettingsResponse,
    summary="How we are notified",
)
async def get_settings_route(ctx: ContextDep, session: SessionDep) -> NotificationSettingsResponse:
    return _response(await NotificationService(session, ctx.owner_id).settings())


@router.put(
    "/notifications",
    response_model=NotificationSettingsResponse,
    summary="Change how we are notified",
)
async def update_settings(
    body: UpdateNotificationSettings, ctx: ContextDep, session: SessionDep
) -> NotificationSettingsResponse:
    row = await NotificationService(session, ctx.owner_id).update(**body.model_dump())
    return _response(row)


@router.post(
    "/notifications/test",
    response_model=TestResult,
    summary="Send a test message on every enabled channel",
)
async def send_test(ctx: ContextDep, session: SessionDep) -> TestResult:
    result = await NotificationService(session, ctx.owner_id).send_test(ctx.user)
    return TestResult(email=result.get("email", "off"), slack=result.get("slack", "off"))
