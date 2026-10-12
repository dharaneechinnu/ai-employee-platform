"""Microsoft 365: Outlook mail, Outlook calendar and OneDrive, through
Microsoft Graph. One one-click connection covers all eight tools.

OneDrive is read-only by scope (`Files.Read.All`), so the token itself
cannot change or delete a file.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.agent.tools.base import SideEffect, ToolContext, ToolResult
from app.agent.tools.packs._http import ApiTool, clip, html_to_text, request
from app.agent.tools.registry import register

GRAPH = "https://graph.microsoft.com/v1.0/me"
TEXT_TYPES = (".txt", ".md", ".csv", ".json", ".log", ".html", ".xml")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _recipients(addresses: list[str]) -> list[dict[str, Any]]:
    return [{"emailAddress": {"address": a}} for a in addresses]


def _sender(msg: dict[str, Any]) -> str | None:
    addr = (msg.get("from") or {}).get("emailAddress") or {}
    name, email = addr.get("name"), addr.get("address")
    return f"{name} <{email}>" if name and email else email or name


def _docx_text(data: bytes) -> str:
    """The words of a Word document, without a parsing library: a .docx
    is a zip, and the text lives in word/document.xml."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode(errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml).strip()


# ------------------------------------------------------------------ mail


class OutlookSearchArgs(BaseModel):
    query: str = Field(
        default="",
        max_length=300,
        description="Words to search for in mail. Empty means the latest messages.",
    )
    max_results: int = Field(default=10, ge=1, le=25)


@register
class OutlookSearch(ApiTool):
    name = "outlook_search"
    pack = "microsoft"
    description = "Search the connected Outlook mailbox. Returns sender, subject, date and preview."
    args_model = OutlookSearchArgs
    side_effect = SideEffect.READ
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: OutlookSearchArgs) -> ToolResult:
        params: dict[str, Any] = {
            "$top": args.max_results,
            "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead",
        }
        if args.query:
            # Graph does not allow $orderby together with $search.
            params["$search"] = '"' + args.query.replace('"', "") + '"'
        else:
            params["$orderby"] = "receivedDateTime desc"
        data = await request(ctx, "GET", f"{GRAPH}/messages", params=params)
        messages = [
            {
                "id": m["id"],
                "from": _sender(m),
                "subject": m.get("subject"),
                "date": m.get("receivedDateTime"),
                "preview": m.get("bodyPreview"),
                "unread": not m.get("isRead", True),
            }
            for m in data.get("value", [])
        ]
        return ToolResult.success({"messages": messages, "count": len(messages)})


class OutlookReadArgs(BaseModel):
    message_id: str = Field(min_length=1, max_length=500)


@register
class OutlookRead(ApiTool):
    name = "outlook_read"
    pack = "microsoft"
    description = "Read one Outlook message in full, by the id outlook_search returned."
    args_model = OutlookReadArgs
    side_effect = SideEffect.READ
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: OutlookReadArgs) -> ToolResult:
        m = await request(
            ctx,
            "GET",
            f"{GRAPH}/messages/{args.message_id}",
            params={"$select": "id,subject,from,toRecipients,receivedDateTime,body"},
            headers={"Prefer": 'outlook.body-content-type="text"'},
        )
        body = m.get("body") or {}
        text = body.get("content", "")
        if body.get("contentType") == "html":
            text = html_to_text(text)
        return ToolResult.success(
            {
                "id": m["id"],
                "from": _sender(m),
                "to": [r["emailAddress"]["address"] for r in m.get("toRecipients", [])],
                "subject": m.get("subject"),
                "date": m.get("receivedDateTime"),
                "body": clip(text),
            }
        )


class OutlookComposeArgs(BaseModel):
    to: list[EmailStr] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20_000)


def _message(args: OutlookComposeArgs) -> dict[str, Any]:
    return {
        "subject": args.subject,
        "body": {"contentType": "Text", "content": args.body},
        "toRecipients": _recipients(list(args.to)),
    }


@register
class OutlookCreateDraft(ApiTool):
    name = "outlook_create_draft"
    pack = "microsoft"
    description = (
        "Save an email as an Outlook draft for a person to review and send. "
        "Prefer this to sending when unsure."
    )
    args_model = OutlookComposeArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: OutlookComposeArgs) -> ToolResult:
        if ctx.dry_run:
            return ToolResult.success(
                {"dry_run": True, "would_draft": {"to": args.to, "subject": args.subject}}
            )
        draft = await request(ctx, "POST", f"{GRAPH}/messages", json=_message(args))
        return ToolResult.success({"draft_id": draft.get("id"), "saved": True})


@register
class OutlookSend(ApiTool):
    name = "outlook_send"
    pack = "microsoft"
    description = "Send an email from the connected Outlook account. It cannot be unsent."
    args_model = OutlookComposeArgs
    side_effect = SideEffect.DESTRUCTIVE
    supports_dry_run = True
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: OutlookComposeArgs) -> ToolResult:
        if ctx.dry_run:
            return ToolResult.success(
                {"dry_run": True, "would_send": {"to": args.to, "subject": args.subject}}
            )
        await request(
            ctx,
            "POST",
            f"{GRAPH}/sendMail",
            json={"message": _message(args), "saveToSentItems": True},
        )
        return ToolResult.success({"sent": True})


# ------------------------------------------------------------------ calendar


class OutlookCalendarListArgs(BaseModel):
    days_ahead: int = Field(default=7, ge=1, le=60)
    max_results: int = Field(default=20, ge=1, le=50)


@register
class OutlookCalendarList(ApiTool):
    name = "outlook_calendar_list"
    pack = "microsoft"
    description = "List upcoming events on the connected Outlook calendar (times in UTC)."
    args_model = OutlookCalendarListArgs
    side_effect = SideEffect.READ
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: OutlookCalendarListArgs) -> ToolResult:
        now = datetime.now(UTC)
        data = await request(
            ctx,
            "GET",
            f"{GRAPH}/calendarView",
            params={
                "startDateTime": _utc(now),
                "endDateTime": _utc(now + timedelta(days=args.days_ahead)),
                "$top": args.max_results,
                "$orderby": "start/dateTime",
                "$select": "id,subject,start,end,location,attendees,webLink",
            },
            headers={"Prefer": 'outlook.timezone="UTC"'},
        )
        events = [
            {
                "id": e.get("id"),
                "title": e.get("subject"),
                "start": (e.get("start") or {}).get("dateTime"),
                "end": (e.get("end") or {}).get("dateTime"),
                "location": (e.get("location") or {}).get("displayName"),
                "attendees": [
                    a["emailAddress"]["address"]
                    for a in e.get("attendees", [])
                    if a.get("emailAddress")
                ],
                "link": e.get("webLink"),
            }
            for e in data.get("value", [])
        ]
        return ToolResult.success({"events": events, "count": len(events)})


class OutlookCalendarCreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start: datetime = Field(description="ISO 8601, e.g. 2026-10-14T15:00:00+05:30")
    end: datetime = Field(description="ISO 8601; must be after start")
    description: str = Field(default="", max_length=5000)
    attendees: list[EmailStr] = Field(default_factory=list, max_length=50)


@register
class OutlookCalendarCreate(ApiTool):
    name = "outlook_calendar_create"
    pack = "microsoft"
    description = "Create an event on the connected Outlook calendar. Attendees are invited."
    args_model = OutlookCalendarCreateArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: OutlookCalendarCreateArgs) -> ToolResult:
        if args.end <= args.start:
            return ToolResult.failure("invalid_arguments", "end must be after start.")
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_create": args.title})
        event = await request(
            ctx,
            "POST",
            f"{GRAPH}/events",
            json={
                "subject": args.title,
                "body": {"contentType": "Text", "content": args.description},
                "start": {"dateTime": _utc(args.start), "timeZone": "UTC"},
                "end": {"dateTime": _utc(args.end), "timeZone": "UTC"},
                "attendees": [
                    {"emailAddress": {"address": a}, "type": "required"} for a in args.attendees
                ],
            },
        )
        return ToolResult.success({"event_id": event.get("id"), "link": event.get("webLink")})


# ------------------------------------------------------------------ OneDrive


class OneDriveSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    max_results: int = Field(default=10, ge=1, le=25)


@register
class OneDriveSearch(ApiTool):
    name = "onedrive_search"
    pack = "microsoft"
    description = "Search the connected OneDrive by file name and contents."
    args_model = OneDriveSearchArgs
    side_effect = SideEffect.READ
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: OneDriveSearchArgs) -> ToolResult:
        term = args.query.replace("'", "''")
        data = await request(
            ctx,
            "GET",
            f"{GRAPH}/drive/root/search(q='{term}')",
            params={"$top": args.max_results},
        )
        files = [
            {
                "id": f["id"],
                "name": f.get("name"),
                "type": (f.get("file") or {}).get("mimeType") or "folder",
                "modified": f.get("lastModifiedDateTime"),
                "link": f.get("webUrl"),
            }
            for f in data.get("value", [])
        ]
        return ToolResult.success({"files": files, "count": len(files)})


class OneDriveReadArgs(BaseModel):
    file_id: str = Field(min_length=1, max_length=500)


@register
class OneDriveRead(ApiTool):
    name = "onedrive_read"
    pack = "microsoft"
    description = "Read the text of a OneDrive file by id: Word documents and plain-text files."
    args_model = OneDriveReadArgs
    side_effect = SideEffect.READ
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: OneDriveReadArgs) -> ToolResult:
        meta = await request(ctx, "GET", f"{GRAPH}/drive/items/{args.file_id}")
        name: str = meta.get("name", "")
        mime = (meta.get("file") or {}).get("mimeType", "")
        is_docx = mime == DOCX or name.lower().endswith(".docx")
        if not (is_docx or mime.startswith("text/") or name.lower().endswith(TEXT_TYPES)):
            return ToolResult.failure(
                "unsupported", f"'{name}' is a {mime or 'binary'} file, which cannot be read."
            )
        if (meta.get("size") or 0) > 10_000_000:
            return ToolResult.failure("too_large", f"'{name}' is larger than 10 MB.")

        content = await request(ctx, "GET", f"{GRAPH}/drive/items/{args.file_id}/content", raw=True)
        try:
            text = _docx_text(content) if is_docx else content.decode(errors="replace")
        except (zipfile.BadZipFile, KeyError):
            return ToolResult.failure("unreadable", f"'{name}' could not be read as a document.")
        return ToolResult.success({"name": name, "text": clip(text)})
