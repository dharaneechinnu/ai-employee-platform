"""The tools added for calendars, mail, Excel, PDFs in Drive and team chat,
against fake APIs. As with the other app tools, what matters is our side:
the right call is made, the person's limits hold, and a dry run touches
nothing."""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.agent.tools import Grant, ToolContext, registry
from app.agent.tools.base import SideEffect
from tests.unit.pdf_sample import make_pdf

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], list[httpx.Request]]:
    import app.agent.tools.packs._http as http_mod
    import app.agent.tools.packs.chat as chat_mod

    def install(handler: Handler) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(recording))  # noqa: E731
        monkeypatch.setattr(http_mod, "_client", client)
        monkeypatch.setattr(chat_mod, "_client", client)
        return seen

    return install


def _ctx(kind: str = "google", credential: str = "tok-123", **kwargs: Any) -> ToolContext:
    return ToolContext(
        owner_id=uuid.uuid4(),
        grants={kind: Grant(credential=credential, config={"account": "me@acme.com"})},
        **kwargs,
    )


async def _run(name: str, ctx: ToolContext, args: dict[str, Any]) -> Any:
    tool = registry.get(name)
    assert tool is not None, name
    return await tool().execute(ctx, args)


def _body(request: httpx.Request) -> Any:
    return json.loads(request.content) if request.content else None


# ------------------------------------------------------------------ calendars


def test_cancelling_an_event_is_marked_as_cannot_be_undone() -> None:
    for name in ("google_calendar_cancel", "outlook_calendar_cancel"):
        tool = registry.get(name)
        assert tool is not None and tool.side_effect is SideEffect.DESTRUCTIVE
    for name in ("google_calendar_update", "outlook_calendar_update"):
        tool = registry.get(name)
        assert tool is not None and tool.side_effect is SideEffect.WRITE


async def test_moving_a_google_event_tells_the_attendees(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200, json={"id": "e1", "summary": "Standup"}))
    result = await _run(
        "google_calendar_update",
        _ctx(),
        {
            "event_id": "e1",
            "start": "2026-11-02T10:00:00+05:30",
            "end": "2026-11-02T10:30:00+05:30",
        },
    )
    assert result.ok, result.message
    assert seen[0].method == "PATCH" and seen[0].url.params["sendUpdates"] == "all"
    assert set(_body(seen[0])) == {"start", "end"}


@pytest.mark.parametrize("tool", ["google_calendar_update", "outlook_calendar_update"])
async def test_a_move_needs_both_times(fake_api: Any, tool: str) -> None:
    seen = fake_api(lambda r: httpx.Response(200, json={}))
    kind = "google" if tool.startswith("google") else "microsoft"
    result = await _run(tool, _ctx(kind), {"event_id": "e1", "start": "2026-11-02T10:00:00Z"})
    assert not result.ok and result.error_class == "invalid_arguments"
    assert not seen


async def test_adding_attendees_keeps_the_ones_already_invited(fake_api: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"attendees": [{"email": "a@x.com"}]})
        return httpx.Response(200, json={"id": "e1"})

    seen = fake_api(handler)
    result = await _run(
        "google_calendar_update", _ctx(), {"event_id": "e1", "add_attendees": ["b@x.com"]}
    )
    assert result.ok, result.message
    emails = [a["email"] for a in _body(seen[-1])["attendees"]]
    assert emails == ["a@x.com", "b@x.com"]


async def test_cancelling_an_outlook_event_deletes_it(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(204))
    result = await _run("outlook_calendar_cancel", _ctx("microsoft"), {"event_id": "AAMk="})
    assert result.ok and result.data["cancelled"] is True
    assert seen[0].method == "DELETE" and seen[0].url.path.endswith("/events/AAMk=")


async def test_a_dry_run_cancel_touches_nothing(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(204))
    result = await _run("google_calendar_cancel", _ctx(dry_run=True), {"event_id": "e1"})
    assert result.ok and result.data["dry_run"] is True
    assert not seen


# ------------------------------------------------------------------ mail


async def test_a_gmail_reply_stays_in_its_thread(fake_api: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "threadId": "t9",
                    "payload": {"headers": [{"name": "Message-ID", "value": "<abc@mail>"}]},
                },
            )
        return httpx.Response(200, json={"id": "d1"})

    seen = fake_api(handler)
    result = await _run(
        "gmail_create_draft",
        _ctx(),
        {
            "to": ["alice@example.com"],
            "subject": "Re: Invoice",
            "body": "Thanks, paid today.",
            "reply_to_message_id": "m1",
        },
    )
    assert result.ok, result.message
    message = _body(seen[-1])["message"]
    assert message["threadId"] == "t9"
    raw = base64.urlsafe_b64decode(message["raw"]).decode()
    assert "In-Reply-To: <abc@mail>" in raw and "References: <abc@mail>" in raw


async def test_tidying_gmail_creates_a_missing_label_and_archives(fake_api: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"labels": [{"id": "L1", "name": "Receipts"}]})
        if request.url.path.endswith("/labels"):
            return httpx.Response(200, json={"id": "L2", "name": "Invoices"})
        return httpx.Response(204)

    seen = fake_api(handler)
    result = await _run(
        "gmail_organize",
        _ctx(),
        {
            "message_ids": ["m1", "m2"],
            "archive": True,
            "mark_read": True,
            "add_labels": ["receipts", "Invoices"],
        },
    )
    assert result.ok, result.message
    change = _body(seen[-1])
    assert seen[-1].url.path.endswith("/messages/batchModify")
    assert change["ids"] == ["m1", "m2"]
    assert set(change["removeLabelIds"]) == {"INBOX", "UNREAD"}
    assert set(change["addLabelIds"]) == {"L1", "L2"}


async def test_tidying_with_nothing_to_do_is_refused(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(204))
    result = await _run("gmail_organize", _ctx(), {"message_ids": ["m1"]})
    assert not result.ok and not seen


async def test_an_outlook_reply_uses_the_conversation(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(202, json={}))
    result = await _run(
        "outlook_send",
        _ctx("microsoft"),
        {"to": ["a@x.com"], "subject": "Re: hi", "body": "Done.", "reply_to_message_id": "M1"},
    )
    assert result.ok, result.message
    assert seen[0].url.path.endswith("/messages/M1/reply")
    assert _body(seen[0])["comment"] == "Done."


async def test_outlook_archives_after_marking_read(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200, json={}))
    result = await _run(
        "outlook_organize",
        _ctx("microsoft"),
        {"message_ids": ["M1"], "archive": True, "mark_read": True},
    )
    assert result.ok, result.message
    assert [r.method for r in seen] == ["PATCH", "POST"]
    assert _body(seen[0]) == {"isRead": True}
    assert _body(seen[1]) == {"destinationId": "archive"}


# ------------------------------------------------------------------ Excel


def _excel(used: dict[str, Any]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/worksheets"):
            return httpx.Response(200, json={"value": [{"name": "Leads"}, {"name": "Notes"}]})
        if "usedRange" in path:
            return httpx.Response(200, json=used)
        return httpx.Response(200, json={"address": "Leads!A5:B6"})

    return handler


async def test_excel_read_lists_sheets_and_rows(fake_api: Any) -> None:
    fake_api(_excel({"address": "Leads!A1:B2", "values": [["Name", "City"], ["Ravi", "Chennai"]]}))
    result = await _run("excel_read", _ctx("microsoft"), {"file_id": "F1"})
    assert result.ok, result.message
    assert result.data["sheets"] == ["Leads", "Notes"]
    assert result.data["rows"][1] == ["Ravi", "Chennai"]


async def test_excel_rows_go_below_the_last_filled_row(fake_api: Any) -> None:
    seen = fake_api(_excel({"address": "Leads!A1:B4", "values": [["x"]] * 4}))
    result = await _run(
        "excel_append_rows",
        _ctx("microsoft"),
        {"file_id": "F1", "rows": [["Priya", "Pune"], ["Arjun"]]},
    )
    assert result.ok, result.message
    write = seen[-1]
    assert write.method == "PATCH" and "range(address='A5:B6')" in write.url.path
    assert _body(write)["values"] == [["Priya", "Pune"], ["Arjun", ""]]


async def test_an_empty_excel_sheet_starts_at_the_top(fake_api: Any) -> None:
    seen = fake_api(_excel({"address": "Leads!A1", "values": [[""]]}))
    await _run("excel_append_rows", _ctx("microsoft"), {"file_id": "F1", "rows": [["a"]]})
    assert "range(address='A1:A1')" in seen[-1].url.path


async def test_excel_cannot_blank_cells(fake_api: Any) -> None:
    seen = fake_api(_excel({}))
    result = await _run(
        "excel_update_cells", _ctx("microsoft"), {"file_id": "F1", "cell": "B3", "values": [[""]]}
    )
    assert not result.ok and result.error_class == "not_allowed"
    assert not seen


async def test_excel_update_writes_the_right_block(fake_api: Any) -> None:
    seen = fake_api(_excel({}))
    result = await _run(
        "excel_update_cells",
        _ctx("microsoft"),
        {"file_id": "F1", "sheet": "Leads", "cell": "c7", "values": [["Won", 5000]]},
    )
    assert result.ok, result.message
    assert "range(address='C7:D7')" in seen[-1].url.path


# ------------------------------------------------------------------ PDFs in Drive


async def test_a_pdf_in_google_drive_is_read(fake_api: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("alt") == "media":
            return httpx.Response(200, content=make_pdf("Signed contract"))
        return httpx.Response(
            200, json={"id": "f1", "name": "Contract.pdf", "mimeType": "application/pdf"}
        )

    fake_api(handler)
    result = await _run("google_drive_read", _ctx(), {"file_id": "f1"})
    assert result.ok, result.message
    assert "Signed contract" in result.data["text"]


async def test_a_pdf_in_onedrive_is_read(fake_api: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/content"):
            return httpx.Response(200, content=make_pdf("Board minutes"))
        return httpx.Response(
            200, json={"name": "Minutes.pdf", "size": 900, "file": {"mimeType": "application/pdf"}}
        )

    fake_api(handler)
    result = await _run("onedrive_read", _ctx("microsoft"), {"file_id": "f1"})
    assert result.ok, result.message
    assert "Board minutes" in result.data["text"]


# ------------------------------------------------------------------ team chat

SLACK_HOOK = "https://hooks.slack.com/services/T0/B0/xyz"
TEAMS_HOOK = "https://prod-01.westus.logic.azure.com/workflows/abc/triggers/manual/paths/invoke"


async def test_slack_gets_the_message_text(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200, text="ok"))
    result = await _run(
        "slack_post", _ctx("slack", SLACK_HOOK), {"title": "Daily", "text": "3 new leads"}
    )
    assert result.ok, result.message
    assert str(seen[0].url) == SLACK_HOOK
    assert _body(seen[0]) == {"text": "*Daily*\n3 new leads"}


async def test_teams_gets_an_adaptive_card(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(202))
    result = await _run("teams_post", _ctx("teams", TEAMS_HOOK), {"text": "Build is green"})
    assert result.ok, result.message
    card = _body(seen[0])["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard" and card["body"][-1]["text"] == "Build is green"


async def test_a_webhook_for_somewhere_else_is_never_called(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200))
    result = await _run("slack_post", _ctx("slack", "https://evil.example/hook"), {"text": "x"})
    assert not result.ok and not seen


async def test_a_removed_webhook_says_to_reconnect(fake_api: Any) -> None:
    fake_api(lambda r: httpx.Response(404, text="no_service"))
    result = await _run("slack_post", _ctx("slack", SLACK_HOOK), {"text": "x"})
    assert not result.ok and result.error_class == "auth_expired"


def test_posting_to_a_channel_asks_first_by_default() -> None:
    for name in ("slack_post", "teams_post"):
        tool = registry.get(name)
        assert tool is not None and tool.side_effect is SideEffect.DESTRUCTIVE


@pytest.mark.parametrize(
    ("kind", "url", "ok"),
    [
        ("slack", SLACK_HOOK, True),
        ("slack", "https://hooks.slack.com.evil.io/x", False),
        ("teams", TEAMS_HOOK, True),
        ("teams", "https://acme.webhook.office.com/webhookb2/x", True),
        ("teams", "http://prod-01.westus.logic.azure.com/x", False),
        ("teams", "https://logic.azure.com.evil.io/x", False),
    ],
)
def test_only_real_slack_and_teams_webhooks_are_accepted(kind: str, url: str, ok: bool) -> None:
    from app.agent.tools.packs.chat import webhook_problem

    assert (webhook_problem(kind, url) is None) is ok
