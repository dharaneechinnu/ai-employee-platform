"""Google Workspace: Gmail, Google Calendar and Google Drive.

All these tools share one one-click connection. Drive is read-only by
scope, not just by tool: the token cannot change or delete a file even
if a tool tried to.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.agent.tools.base import SideEffect, ToolContext, ToolResult
from app.agent.tools.packs._http import (
    ApiTool,
    b64url_decode,
    clip,
    html_to_text,
    is_pdf,
    pdf_text,
    request,
)
from app.agent.tools.registry import register

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary"
DRIVE = "https://www.googleapis.com/drive/v3"

# Google's own formats have no bytes to download; they are exported.
DRIVE_EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _body_text(payload: dict[str, Any]) -> str:
    """Walk a MIME tree for the best readable body: plain text first,
    HTML stripped to text if that is all there is."""
    plain: list[str] = []
    rich: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(b64url_decode(data).decode(errors="replace"))
        elif data and mime == "text/html":
            rich.append(html_to_text(b64url_decode(data).decode(errors="replace")))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return "\n".join(plain) if plain else "\n".join(rich)


def _raw_message(
    ctx: ToolContext,
    to: list[str],
    subject: str,
    body: str,
    extra: dict[str, str] | None = None,
) -> str:
    message = EmailMessage()
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    for name, value in (extra or {}).items():
        message[name] = value
    account = (ctx.config or {}).get("account")
    if account:
        message["From"] = account
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


# ------------------------------------------------------------------ Gmail


class GmailSearchArgs(BaseModel):
    query: str = Field(
        default="",
        max_length=500,
        description="Gmail search syntax, e.g. 'from:alice is:unread newer_than:7d'. "
        "Empty means the latest messages.",
    )
    max_results: int = Field(default=10, ge=1, le=25)


@register
class GmailSearch(ApiTool):
    name = "gmail_search"
    pack = "google"
    description = "Search the connected Gmail inbox. Returns sender, subject, date and a snippet."
    args_model = GmailSearchArgs
    side_effect = SideEffect.READ
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: GmailSearchArgs) -> ToolResult:
        listing = await request(
            ctx,
            "GET",
            f"{GMAIL}/messages",
            params={"q": args.query, "maxResults": args.max_results},
        )
        found = []
        for item in listing.get("messages", []):
            msg = await request(
                ctx,
                "GET",
                f"{GMAIL}/messages/{item['id']}",
                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
            h = _headers(msg.get("payload", {}))
            found.append(
                {
                    "id": msg["id"],
                    "from": h.get("from"),
                    "subject": h.get("subject"),
                    "date": h.get("date"),
                    "snippet": msg.get("snippet"),
                    "unread": "UNREAD" in msg.get("labelIds", []),
                }
            )
        return ToolResult.success({"messages": found, "count": len(found)})


class GmailReadArgs(BaseModel):
    message_id: str = Field(min_length=1, max_length=200)


@register
class GmailRead(ApiTool):
    name = "gmail_read"
    pack = "google"
    description = "Read one Gmail message in full, by the id gmail_search returned."
    args_model = GmailReadArgs
    side_effect = SideEffect.READ
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: GmailReadArgs) -> ToolResult:
        msg = await request(
            ctx, "GET", f"{GMAIL}/messages/{args.message_id}", params={"format": "full"}
        )
        payload = msg.get("payload", {})
        h = _headers(payload)
        return ToolResult.success(
            {
                "id": msg["id"],
                "thread_id": msg.get("threadId"),
                "from": h.get("from"),
                "to": h.get("to"),
                "subject": h.get("subject"),
                "date": h.get("date"),
                "body": clip(_body_text(payload)),
            }
        )


class GmailComposeArgs(BaseModel):
    to: list[EmailStr] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20_000)
    reply_to_message_id: str | None = Field(
        default=None,
        max_length=200,
        description="To answer an email in its own thread, the id gmail_search returned",
    )


async def _compose(ctx: ToolContext, args: GmailComposeArgs) -> dict[str, Any]:
    """The Gmail message to save or send. A reply carries the headers that
    keep it in the original's thread, in Gmail and in the other person's
    mail app too."""
    extra: dict[str, str] = {}
    thread_id = None
    if args.reply_to_message_id:
        original = await request(
            ctx,
            "GET",
            f"{GMAIL}/messages/{args.reply_to_message_id}",
            params={"format": "metadata", "metadataHeaders": ["Message-ID", "References"]},
        )
        h = _headers(original.get("payload", {}))
        thread_id = original.get("threadId")
        if message_id := h.get("message-id"):
            extra["In-Reply-To"] = message_id
            extra["References"] = (
                f"{h['references']} {message_id}" if h.get("references") else message_id
            )
    message: dict[str, Any] = {
        "raw": _raw_message(ctx, list(args.to), args.subject, args.body, extra)
    }
    if thread_id:
        message["threadId"] = thread_id
    return message


@register
class GmailCreateDraft(ApiTool):
    name = "gmail_create_draft"
    pack = "google"
    description = (
        "Save an email as a Gmail draft for a person to review and send. "
        "Prefer this to sending when unsure. To answer an email, pass reply_to_message_id "
        "so the draft stays in its thread."
    )
    args_model = GmailComposeArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: GmailComposeArgs) -> ToolResult:
        if ctx.dry_run:
            return ToolResult.success(
                {"dry_run": True, "would_draft": {"to": args.to, "subject": args.subject}}
            )
        draft = await request(
            ctx,
            "POST",
            f"{GMAIL}/drafts",
            json={"message": await _compose(ctx, args)},
        )
        return ToolResult.success({"draft_id": draft.get("id"), "saved": True})


@register
class GmailSend(ApiTool):
    name = "gmail_send"
    pack = "google"
    description = (
        "Send an email from the connected Gmail account. It cannot be unsent. To answer an "
        "email, pass reply_to_message_id so it goes in the same thread."
    )
    args_model = GmailComposeArgs
    # Destructive: an email that has gone cannot be taken back.
    side_effect = SideEffect.DESTRUCTIVE
    supports_dry_run = True
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: GmailComposeArgs) -> ToolResult:
        if ctx.dry_run:
            return ToolResult.success(
                {"dry_run": True, "would_send": {"to": args.to, "subject": args.subject}}
            )
        sent = await request(
            ctx,
            "POST",
            f"{GMAIL}/messages/send",
            json=await _compose(ctx, args),
        )
        return ToolResult.success({"message_id": sent.get("id"), "sent": True})


class GmailOrganizeArgs(BaseModel):
    message_ids: list[str] = Field(min_length=1, max_length=50, description="Ids from gmail_search")
    archive: bool = Field(default=False, description="Take them out of the inbox")
    mark_read: bool | None = Field(default=None, description="true: mark read; false: unread")
    star: bool | None = Field(default=None, description="true: star; false: unstar")
    add_labels: list[str] = Field(
        default_factory=list, max_length=10, description="Label names; new ones are created"
    )
    remove_labels: list[str] = Field(default_factory=list, max_length=10)


@register
class GmailOrganize(ApiTool):
    name = "gmail_organize"
    pack = "google"
    description = (
        "Tidy Gmail messages: archive them, mark them read or unread, star them, or add and "
        "remove labels. Nothing is deleted, and every change can be undone in Gmail."
    )
    args_model = GmailOrganizeArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: GmailOrganizeArgs) -> ToolResult:
        add: list[str] = []
        remove: list[str] = []
        if args.archive:
            remove.append("INBOX")
        if args.mark_read is not None:
            (remove if args.mark_read else add).append("UNREAD")
        if args.star is not None:
            (add if args.star else remove).append("STARRED")
        if not (add or remove or args.add_labels or args.remove_labels):
            return ToolResult.failure("invalid_arguments", "Nothing to change was given.")
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_change": len(args.message_ids)})
        if args.add_labels or args.remove_labels:
            labels = await request(ctx, "GET", f"{GMAIL}/labels")
            by_name = {lab["name"].lower(): lab["id"] for lab in labels.get("labels", [])}
            for name in args.add_labels:
                label_id = by_name.get(name.lower())
                if label_id is None:
                    made = await request(ctx, "POST", f"{GMAIL}/labels", json={"name": name})
                    label_id = made["id"]
                add.append(label_id)
            remove += [by_name[n.lower()] for n in args.remove_labels if n.lower() in by_name]
        await request(
            ctx,
            "POST",
            f"{GMAIL}/messages/batchModify",
            json={"ids": args.message_ids, "addLabelIds": add, "removeLabelIds": remove},
        )
        return ToolResult.success({"changed": len(args.message_ids)})


# ------------------------------------------------------------------ Calendar


class CalendarListArgs(BaseModel):
    days_ahead: int = Field(default=7, ge=0, le=60)
    days_back: int = Field(
        default=0, ge=0, le=60, description="Also include events from this many days ago"
    )
    query: str = Field(default="", max_length=200, description="Optional text to match")
    max_results: int = Field(default=20, ge=1, le=50)


@register
class GoogleCalendarList(ApiTool):
    name = "google_calendar_list"
    pack = "google"
    description = (
        "List events on the connected Google Calendar: upcoming ones, and past ones "
        "with days_back (e.g. last week's meetings)."
    )
    args_model = CalendarListArgs
    side_effect = SideEffect.READ
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: CalendarListArgs) -> ToolResult:
        now = datetime.now(UTC)
        params: dict[str, Any] = {
            "timeMin": _iso(now - timedelta(days=args.days_back)),
            "timeMax": _iso(now + timedelta(days=args.days_ahead)),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": args.max_results,
        }
        if args.query:
            params["q"] = args.query
        data = await request(ctx, "GET", f"{CALENDAR}/events", params=params)
        events = [
            {
                "id": e.get("id"),
                "title": e.get("summary"),
                "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
                "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
                "location": e.get("location"),
                "attendees": [a.get("email") for a in e.get("attendees", [])],
                "link": e.get("htmlLink"),
            }
            for e in data.get("items", [])
        ]
        return ToolResult.success({"events": events, "count": len(events)})


class CalendarCreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start: datetime = Field(description="ISO 8601, e.g. 2026-10-14T15:00:00+05:30")
    end: datetime = Field(description="ISO 8601; must be after start")
    description: str = Field(default="", max_length=5000)
    attendees: list[EmailStr] = Field(default_factory=list, max_length=50)


@register
class GoogleCalendarCreate(ApiTool):
    name = "google_calendar_create"
    pack = "google"
    description = (
        "Create an event on the connected Google Calendar. Attendees receive an invitation."
    )
    args_model = CalendarCreateArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: CalendarCreateArgs) -> ToolResult:
        if args.end <= args.start:
            return ToolResult.failure("invalid_arguments", "end must be after start.")
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_create": args.title})
        event = await request(
            ctx,
            "POST",
            f"{CALENDAR}/events",
            params={"sendUpdates": "all" if args.attendees else "none"},
            json={
                "summary": args.title,
                "description": args.description,
                "start": {"dateTime": _iso(args.start)},
                "end": {"dateTime": _iso(args.end)},
                "attendees": [{"email": a} for a in args.attendees],
            },
        )
        return ToolResult.success({"event_id": event.get("id"), "link": event.get("htmlLink")})


class CalendarUpdateArgs(BaseModel):
    event_id: str = Field(min_length=1, max_length=300, description="The id from the calendar list")
    title: str | None = Field(default=None, max_length=300)
    start: datetime | None = Field(default=None, description="New start, ISO 8601 with offset")
    end: datetime | None = Field(default=None, description="New end, ISO 8601 with offset")
    description: str | None = Field(default=None, max_length=5000)
    add_attendees: list[EmailStr] = Field(default_factory=list, max_length=50)


def _check_times(start: datetime | None, end: datetime | None) -> str | None:
    if (start is None) != (end is None):
        return "Give both start and end when moving an event, so its length is clear."
    if start is not None and end is not None and end <= start:
        return "end must be after start."
    return None


@register
class GoogleCalendarUpdate(ApiTool):
    name = "google_calendar_update"
    pack = "google"
    description = (
        "Change an event on the connected Google Calendar: move it to a new time, rename it, "
        "change its description or invite more people. Attendees are told about the change."
    )
    args_model = CalendarUpdateArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: CalendarUpdateArgs) -> ToolResult:
        if problem := _check_times(args.start, args.end):
            return ToolResult.failure("invalid_arguments", problem)
        patch: dict[str, Any] = {}
        if args.title is not None:
            patch["summary"] = args.title
        if args.description is not None:
            patch["description"] = args.description
        if args.start is not None and args.end is not None:
            patch["start"] = {"dateTime": _iso(args.start)}
            patch["end"] = {"dateTime": _iso(args.end)}
        if not patch and not args.add_attendees:
            return ToolResult.failure("invalid_arguments", "Nothing to change was given.")
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_change": sorted(patch)})
        if args.add_attendees:
            current = await request(ctx, "GET", f"{CALENDAR}/events/{args.event_id}")
            known = {a.get("email") for a in current.get("attendees", [])}
            patch["attendees"] = current.get("attendees", []) + [
                {"email": a} for a in args.add_attendees if a not in known
            ]
        event = await request(
            ctx,
            "PATCH",
            f"{CALENDAR}/events/{args.event_id}",
            params={"sendUpdates": "all"},
            json=patch,
        )
        return ToolResult.success(
            {
                "event_id": event.get("id"),
                "title": event.get("summary"),
                "start": (event.get("start") or {}).get("dateTime"),
                "link": event.get("htmlLink"),
            }
        )


class CalendarCancelArgs(BaseModel):
    event_id: str = Field(min_length=1, max_length=300, description="The id from the calendar list")
    notify: bool = Field(default=True, description="Tell the attendees it is cancelled")


@register
class GoogleCalendarCancel(ApiTool):
    name = "google_calendar_cancel"
    pack = "google"
    description = (
        "Cancel and remove an event from the connected Google Calendar. Attendees are told "
        "it is cancelled. This cannot be undone."
    )
    args_model = CalendarCancelArgs
    # Destructive: the attendees' invitations are withdrawn for good.
    side_effect = SideEffect.DESTRUCTIVE
    supports_dry_run = True
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: CalendarCancelArgs) -> ToolResult:
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_cancel": args.event_id})
        await request(
            ctx,
            "DELETE",
            f"{CALENDAR}/events/{args.event_id}",
            params={"sendUpdates": "all" if args.notify else "none"},
        )
        return ToolResult.success({"event_id": args.event_id, "cancelled": True})


# ------------------------------------------------------------------ Drive


class DriveSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="Words to look for")
    max_results: int = Field(default=10, ge=1, le=25)


@register
class GoogleDriveSearch(ApiTool):
    name = "google_drive_search"
    pack = "google"
    description = "Search the connected Google Drive by file name and contents."
    args_model = DriveSearchArgs
    side_effect = SideEffect.READ
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: DriveSearchArgs) -> ToolResult:
        # Drive's query language quotes with single quotes; escape them
        # so a search term cannot change the shape of the query.
        term = args.query.replace("\\", "\\\\").replace("'", "\\'")
        data = await request(
            ctx,
            "GET",
            f"{DRIVE}/files",
            params={
                "q": f"(name contains '{term}' or fullText contains '{term}') and trashed = false",
                "pageSize": args.max_results,
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
            },
        )
        files = [
            {
                "id": f["id"],
                "name": f.get("name"),
                "type": f.get("mimeType"),
                "modified": f.get("modifiedTime"),
                "link": f.get("webViewLink"),
            }
            for f in data.get("files", [])
        ]
        return ToolResult.success({"files": files, "count": len(files)})


class DriveReadArgs(BaseModel):
    file_id: str = Field(min_length=1, max_length=200)


@register
class GoogleDriveRead(ApiTool):
    name = "google_drive_read"
    pack = "google"
    description = (
        "Read the text of a Google Drive file by id: Docs, Sheets (as CSV), Slides, "
        "PDFs and plain-text files."
    )
    args_model = DriveReadArgs
    side_effect = SideEffect.READ
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: DriveReadArgs) -> ToolResult:
        meta = await request(
            ctx, "GET", f"{DRIVE}/files/{args.file_id}", params={"fields": "id,name,mimeType"}
        )
        mime = meta.get("mimeType", "")
        if mime in DRIVE_EXPORTS:
            content = await request(
                ctx,
                "GET",
                f"{DRIVE}/files/{args.file_id}/export",
                params={"mimeType": DRIVE_EXPORTS[mime]},
                raw=True,
            )
        elif is_pdf(b"", mime, meta.get("name", "")):
            content = await request(
                ctx, "GET", f"{DRIVE}/files/{args.file_id}", params={"alt": "media"}, raw=True
            )
            try:
                text = await pdf_text(content)
            except ValueError as exc:
                return ToolResult.failure(
                    "unreadable", f"'{meta.get('name')}' cannot be read: {exc}."
                )
            return ToolResult.success({"name": meta.get("name"), "text": clip(text)})
        elif mime.startswith("text/") or mime in ("application/json", "application/csv"):
            content = await request(
                ctx, "GET", f"{DRIVE}/files/{args.file_id}", params={"alt": "media"}, raw=True
            )
        else:
            return ToolResult.failure(
                "unsupported",
                f"'{meta.get('name')}' is a {mime} file, which cannot be read as text.",
            )
        return ToolResult.success(
            {"name": meta.get("name"), "text": clip(content.decode(errors="replace"))}
        )
