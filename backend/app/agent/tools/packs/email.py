"""Email tools.

Note the split in side effects: `save_draft` is a write, `send_email`
is destructive. A draft nobody sends is harmless; a sent email cannot
be unsent. Under the default policy that means drafting happens
automatically and sending always asks a human first — which is most of
the value with none of the danger.
"""

from __future__ import annotations

import email.utils
import imaplib
import smtplib
from email.message import EmailMessage
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import register

MAX_BODY_CHARS = 10_000


def _imap(config: dict[str, Any], password: str) -> imaplib.IMAP4_SSL:
    client = imaplib.IMAP4_SSL(config.get("imap_host", "imap.gmail.com"))
    client.login(config["username"], password)
    return client


def _payload(raw: Any) -> str:
    """Pull the body out of an imaplib fetch response.

    Entries are either bytes or a (spec, payload) tuple depending on
    the fetch arguments, so the shape has to be checked rather than
    assumed.
    """
    if not raw:
        return ""
    first = raw[0]
    if isinstance(first, tuple) and len(first) >= 2 and isinstance(first[1], bytes):
        return first[1].decode(errors="replace")
    if isinstance(first, bytes):
        return first.decode(errors="replace")
    return ""


class ListEmailsArgs(BaseModel):
    folder: str = Field(default="INBOX")
    limit: int = Field(default=10, ge=1, le=50)
    unread_only: bool = False


@register
class ListEmails(Tool):
    name = "list_emails"
    pack = "email"
    description = "List recent emails: sender, subject and date. Does not read bodies."
    args_model = ListEmailsArgs
    side_effect = SideEffect.READ
    requires_connection = "email"
    timeout_s = 30.0

    async def run(self, ctx: ToolContext, args: ListEmailsArgs) -> ToolResult:  # type: ignore[override]
        if not ctx.credential or not ctx.config:
            return ToolResult.failure("not_connected", "No email account is connected.")

        try:
            client = _imap(ctx.config, ctx.credential)
            client.select(args.folder, readonly=True)
            _, data = client.search(None, "UNSEEN" if args.unread_only else "ALL")
            ids = data[0].split()[-args.limit :]

            messages = []
            for msg_id in reversed(ids):
                _, raw = client.fetch(
                    msg_id.decode(), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
                )
                messages.append({"id": msg_id.decode(), "header": _payload(raw).strip()})

            client.logout()
        except (imaplib.IMAP4.error, OSError) as exc:
            return ToolResult.failure("email_error", f"Could not read the inbox: {exc}")

        return ToolResult.success({"folder": args.folder, "messages": messages})


class ReadEmailArgs(BaseModel):
    message_id: str
    folder: str = Field(default="INBOX")


@register
class ReadEmail(Tool):
    name = "read_email"
    pack = "email"
    description = "Read the full text of one email."
    args_model = ReadEmailArgs
    side_effect = SideEffect.READ
    requires_connection = "email"
    timeout_s = 30.0

    async def run(self, ctx: ToolContext, args: ReadEmailArgs) -> ToolResult:  # type: ignore[override]
        if not ctx.credential or not ctx.config:
            return ToolResult.failure("not_connected", "No email account is connected.")

        try:
            client = _imap(ctx.config, ctx.credential)
            client.select(args.folder, readonly=True)
            _, raw = client.fetch(args.message_id, "(RFC822)")
            body = _payload(raw)[:MAX_BODY_CHARS]
            client.logout()
        except (imaplib.IMAP4.error, OSError) as exc:
            return ToolResult.failure("email_error", f"Could not read that email: {exc}")

        return ToolResult.success({"message_id": args.message_id, "content": body})


class DraftArgs(BaseModel):
    to: EmailStr
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=MAX_BODY_CHARS)


@register
class SaveDraft(Tool):
    name = "save_draft"
    pack = "email"
    description = (
        "Save a reply as a draft for a human to review and send. Prefer this over sending directly."
    )
    args_model = DraftArgs
    # A write, not destructive: a draft nobody sends harms nobody, so
    # the default policy lets this happen without asking.
    side_effect = SideEffect.WRITE
    requires_connection = "email"
    supports_dry_run = True
    timeout_s = 30.0

    async def run(self, ctx: ToolContext, args: DraftArgs) -> ToolResult:  # type: ignore[override]
        if not ctx.credential or not ctx.config:
            return ToolResult.failure("not_connected", "No email account is connected.")

        if ctx.dry_run:
            return ToolResult.success(
                {"dry_run": True, "would_draft": {"to": args.to, "subject": args.subject}}
            )

        message = EmailMessage()
        message["From"] = ctx.config["username"]
        message["To"] = args.to
        message["Subject"] = args.subject
        message["Date"] = email.utils.formatdate(localtime=True)
        message.set_content(args.body)

        try:
            client = _imap(ctx.config, ctx.credential)
            client.append(
                ctx.config.get("drafts_folder", "[Gmail]/Drafts"),
                "",
                imaplib.Time2Internaldate(email.utils.localtime().timestamp()),
                message.as_bytes(),
            )
            client.logout()
        except (imaplib.IMAP4.error, OSError) as exc:
            return ToolResult.failure("email_error", f"Could not save the draft: {exc}")

        return ToolResult.success({"saved": True, "to": args.to, "subject": args.subject})


@register
class SendEmail(Tool):
    name = "send_email"
    pack = "email"
    description = (
        "Send an email immediately. This cannot be undone, so it normally "
        "requires a human to approve it first."
    )
    args_model = DraftArgs
    # Destructive: a sent email cannot be recalled. The default policy
    # therefore pauses for a human.
    side_effect = SideEffect.DESTRUCTIVE
    requires_connection = "email"
    supports_dry_run = True
    timeout_s = 30.0

    async def run(self, ctx: ToolContext, args: DraftArgs) -> ToolResult:  # type: ignore[override]
        if not ctx.credential or not ctx.config:
            return ToolResult.failure("not_connected", "No email account is connected.")

        if ctx.dry_run:
            return ToolResult.success(
                {"dry_run": True, "would_send": {"to": args.to, "subject": args.subject}}
            )

        message = EmailMessage()
        message["From"] = ctx.config["username"]
        message["To"] = args.to
        message["Subject"] = args.subject
        message.set_content(args.body)

        try:
            with smtplib.SMTP_SSL(
                ctx.config.get("smtp_host", "smtp.gmail.com"),
                ctx.config.get("smtp_port", 465),
            ) as server:
                server.login(ctx.config["username"], ctx.credential)
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            return ToolResult.failure("email_error", f"Could not send: {exc}")

        return ToolResult.success({"sent": True, "to": args.to, "subject": args.subject})
