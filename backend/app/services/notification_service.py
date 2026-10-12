"""Notifications: tell people when a run needs them or has finished.

Two channels:

- **Email** through the platform's SMTP server, to the people concerned:
  the company's admins when an approval is waiting, the person who
  assigned the task when it ends. Each admin's email carries their own
  signed approval link, so they can decide from their inbox.
- **Slack** through an incoming webhook the company pastes in. Its
  buttons open the same approval page, which asks whoever clicks to
  sign in, because a channel is shared and a link in it must not act
  on its own.

A notification is never allowed to break a run. Every send has a short
timeout and every failure is logged and swallowed: a run that finished
must still be recorded as finished if Slack is down.

Opening an approval link never decides anything. The decision is a
POST from a button on the page, so a mail scanner or a link preview
fetching the URL cannot approve an action by accident.
"""

from __future__ import annotations

import asyncio
import json
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.core.errors import ValidationError
from app.core.observability import get_logger
from app.core.signed import sign
from app.db.models.ai_employee import AIEmployee
from app.db.models.identity import Membership, Role, User
from app.db.models.notification import NotificationSettings
from app.db.models.organization import Organization
from app.db.models.policy import Approval
from app.db.models.task import Run, RunStatus, Task

log = get_logger(__name__)

SEND_TIMEOUT_S = 10.0
SLACK_PREFIX = "https://hooks.slack.com/"


# ------------------------------------------------------------------ transports
# Module-level so tests can replace them without a mail server or Slack.


async def send_email(to: str, subject: str, text: str, html: str) -> None:
    settings = get_settings()
    if not settings.email_notifications_available:
        raise RuntimeError("Email is not configured on this platform.")

    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_username or ""
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    def deliver() -> None:
        host, port = settings.smtp_host or "", settings.smtp_port
        context = ssl.create_default_context()
        server: smtplib.SMTP
        if settings.smtp_use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=SEND_TIMEOUT_S, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=SEND_TIMEOUT_S)
            server.starttls(context=context)
        with server:
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)

    await asyncio.wait_for(asyncio.to_thread(deliver), timeout=SEND_TIMEOUT_S + 5)


async def post_slack(webhook_url: str, payload: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=SEND_TIMEOUT_S) as http:
        resp = await http.post(webhook_url, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"Slack answered {resp.status_code}: {resp.text[:200]}")


# ------------------------------------------------------------------ messages


@dataclass(slots=True)
class Message:
    subject: str
    lines: list[str]
    # (label, url, style) where style is "primary", "danger" or "".
    buttons: list[tuple[str, str, str]]
    detail: str | None = None

    def text(self) -> str:
        parts = [*self.lines]
        if self.detail:
            parts += ["", self.detail]
        parts += ["", *[f"{label}: {url}" for label, url, _ in self.buttons]]
        return "\n".join(parts)

    def html(self) -> str:
        colours = {"primary": "#2B4EE0", "danger": "#C8372D", "": "#4A5070"}
        buttons = "".join(
            f'<a href="{escape(url)}" style="display:inline-block;margin:0 8px 8px 0;'
            f"padding:10px 18px;border-radius:8px;background:{colours[style]};color:#fff;"
            f'text-decoration:none;font-weight:600">{escape(label)}</a>'
            for label, url, style in self.buttons
        )
        detail = (
            f'<pre style="background:#F3F5FB;border-radius:8px;padding:12px;font-size:12px;'
            f'white-space:pre-wrap">{escape(self.detail)}</pre>'
            if self.detail
            else ""
        )
        body = "".join(f"<p style='margin:0 0 10px'>{escape(line)}</p>" for line in self.lines)
        return (
            "<div style=\"font-family:'DM Sans',Arial,sans-serif;color:#0F1430;max-width:560px\">"
            f"<h2 style='font-size:18px;margin:0 0 14px'>{escape(self.subject)}</h2>"
            f"{body}{detail}<div style='margin-top:16px'>{buttons}</div></div>"
        )

    def slack(self) -> dict[str, Any]:
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{self.subject}*"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(self.lines)}},
        ]
        if self.detail:
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": f"```{self.detail}```"}}
            )
        if self.buttons:
            elements = []
            for label, url, style in self.buttons:
                button: dict[str, Any] = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": label},
                    "url": url,
                }
                if style:
                    button["style"] = style
                elements.append(button)
            blocks.append({"type": "actions", "elements": elements})
        return {"text": self.subject, "blocks": blocks}


def _app_url(path: str) -> str:
    return f"{get_settings().public_app_url.rstrip('/')}{path}"


def _humanise(tool_name: str) -> str:
    return tool_name.replace("_", " ")


def approval_link_token(approval: Approval, user_id: uuid.UUID | None) -> str:
    """A link that lets one person decide one approval, until it expires.

    With a user id (email), opening it is enough to decide as that
    person. Without one (Slack), the page asks the clicker to sign in.
    """
    claims: dict[str, Any] = {"apr": str(approval.id), "org": str(approval.org_id)}
    if user_id is not None:
        claims["sub"] = str(user_id)
    return sign("approval_link", claims, expires_at=approval.expires_at)


# ------------------------------------------------------------------ service


class NotificationService:
    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        self.session = session
        self.org_id = org_id

    # --- settings ------------------------------------------------------

    async def settings(self) -> NotificationSettings:
        row = await self.session.scalar(
            select(NotificationSettings).where(NotificationSettings.org_id == self.org_id)
        )
        if row is None:
            # Defaults, not yet saved: email on for every event, Slack
            # off until a webhook is added.
            row = NotificationSettings(
                org_id=self.org_id,
                email_enabled=True,
                slack_enabled=False,
                on_approval_requested=True,
                on_task_completed=True,
                on_task_failed=True,
            )
        return row

    async def update(
        self,
        *,
        email_enabled: bool,
        slack_enabled: bool,
        on_approval_requested: bool,
        on_task_completed: bool,
        on_task_failed: bool,
        slack_webhook_url: str | None,
        clear_slack_webhook: bool,
    ) -> NotificationSettings:
        row = await self.settings()
        row.email_enabled = email_enabled
        row.on_approval_requested = on_approval_requested
        row.on_task_completed = on_task_completed
        row.on_task_failed = on_task_failed

        if clear_slack_webhook:
            row.slack_webhook_enc = None
            row.slack_webhook_last4 = None
        elif slack_webhook_url:
            url = slack_webhook_url.strip()
            # Only Slack's own host: otherwise this would be a way to
            # make the worker POST to any address, internal ones included.
            if not url.startswith(SLACK_PREFIX):
                raise ValidationError(f"A Slack webhook URL starts with {SLACK_PREFIX}")
            row.slack_webhook_enc = encrypt(url, scope=self.org_id)
            row.slack_webhook_last4 = url[-4:]

        row.slack_enabled = slack_enabled and row.slack_webhook_enc is not None
        if row not in self.session:
            self.session.add(row)
        await self.session.flush()
        return row

    def _webhook(self, row: NotificationSettings) -> str | None:
        if not row.slack_enabled or row.slack_webhook_enc is None:
            return None
        return decrypt(row.slack_webhook_enc, scope=self.org_id)

    # --- sending -------------------------------------------------------

    async def send_test(self, user: User) -> dict[str, str]:
        """Send one message on every enabled channel and report each."""
        row = await self.settings()
        message = Message(
            subject="Test notification from your AI Employees",
            lines=["Notifications are working. You will hear here when a run needs you."],
            buttons=[("Open approvals", _app_url("/approvals"), "primary")],
        )
        result: dict[str, str] = {}

        if not row.email_enabled:
            result["email"] = "off"
        elif not get_settings().email_notifications_available:
            result["email"] = "unavailable: email is not configured on this platform"
        else:
            try:
                await send_email(user.email, message.subject, message.text(), message.html())
                result["email"] = f"sent to {user.email}"
            except Exception as exc:  # noqa: BLE001 - reported back to the admin
                result["email"] = f"failed: {exc}"

        webhook = self._webhook(row)
        if webhook is None:
            result["slack"] = "off"
        else:
            try:
                await post_slack(webhook, message.slack())
                result["slack"] = "sent"
            except Exception as exc:  # noqa: BLE001 - reported back to the admin
                result["slack"] = f"failed: {exc}"
        return result

    async def approval_requested(self, approval: Approval) -> None:
        row = await self.settings()
        if not row.on_approval_requested:
            return
        task, employee = await self._task_and_employee(approval.run_id)
        org = await self.session.get(Organization, self.org_id)

        who = employee.name if employee else "An AI Employee"
        subject = f"Approval needed: {who} wants to {_humanise(approval.tool_name)}"
        lines = [
            f"Task: {task.title or task.input[:120]}" if task else "",
            f"Action: {approval.tool_name} ({approval.side_effect})",
            f"Company: {org.name}" if org else "",
            f"The run is paused until someone decides. "
            f"This request expires {approval.expires_at:%d %b %Y, %H:%M} UTC.",
        ]
        detail = json.dumps(approval.proposed, indent=2, default=str)[:1500]

        if row.email_enabled and get_settings().email_notifications_available:
            for admin in await self._admins():
                token = approval_link_token(approval, admin.id)
                link = _app_url(f"/approve/{token}")
                personal = Message(
                    subject=subject,
                    lines=[line for line in lines if line],
                    detail=detail,
                    buttons=[
                        ("Approve", f"{link}?action=approve", "primary"),
                        ("Reject", f"{link}?action=reject", "danger"),
                        ("Open in app", _app_url("/approvals"), ""),
                    ],
                )
                await self._try_email(admin.email, personal)

        webhook = self._webhook(row)
        if webhook:
            link = _app_url(f"/approve/{approval_link_token(approval, None)}")
            shared = Message(
                subject=subject,
                lines=[line for line in lines if line],
                detail=detail,
                buttons=[
                    ("Approve", f"{link}?action=approve", "primary"),
                    ("Reject", f"{link}?action=reject", "danger"),
                ],
            )
            await self._try_slack(webhook, shared)

    async def task_finished(self, task: Task, run: Run) -> None:
        row = await self.settings()
        succeeded = run.status is RunStatus.COMPLETED
        if run.status is RunStatus.CANCELLED:
            return  # the person who cancelled it already knows
        if (succeeded and not row.on_task_completed) or (not succeeded and not row.on_task_failed):
            return

        employee = await self.session.get(AIEmployee, task.employee_id)
        who = employee.name if employee else "Your AI Employee"
        title = task.title or task.input[:80]
        subject = f"{who} finished: {title}" if succeeded else f"{who} could not finish: {title}"
        excerpt = (run.output or "") if succeeded else (run.error_message or run.stop_cause or "")
        message = Message(
            subject=subject,
            lines=[
                "The task is complete." if succeeded else "The task stopped before finishing.",
                f"Steps: {run.step_count}",
            ],
            detail=excerpt[:1200] or None,
            buttons=[("View the run", _app_url(f"/tasks?task={task.id}"), "primary")],
        )

        if row.email_enabled and get_settings().email_notifications_available:
            creator = await self.session.get(User, task.created_by)
            if creator is not None and creator.is_active:
                await self._try_email(creator.email, message)

        webhook = self._webhook(row)
        if webhook:
            await self._try_slack(webhook, message)

    # --- helpers -------------------------------------------------------

    async def _task_and_employee(self, run_id: uuid.UUID) -> tuple[Task | None, AIEmployee | None]:
        run = await self.session.get(Run, run_id)
        task = await self.session.get(Task, run.task_id) if run else None
        employee = await self.session.get(AIEmployee, task.employee_id) if task else None
        return task, employee

    async def _admins(self) -> list[User]:
        rows = await self.session.scalars(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.org_id == self.org_id,
                Membership.role == Role.ADMIN,
                User.is_active.is_(True),
            )
        )
        return list(rows.all())

    async def _try_email(self, to: str, message: Message) -> None:
        try:
            await send_email(to, message.subject, message.text(), message.html())
        except Exception as exc:  # noqa: BLE001 - a notification must never fail a run
            log.warning("notify_email_failed", org_id=str(self.org_id), error=str(exc)[:200])

    async def _try_slack(self, webhook: str, message: Message) -> None:
        try:
            await post_slack(webhook, message.slack())
        except Exception as exc:  # noqa: BLE001 - a notification must never fail a run
            log.warning("notify_slack_failed", org_id=str(self.org_id), error=str(exc)[:200])


async def notify_safely(coro: Any) -> None:
    """Run a notification without letting anything escape it."""
    try:
        await coro
    except Exception as exc:  # noqa: BLE001 - see module docstring
        log.warning("notify_failed", error=str(exc)[:200])
