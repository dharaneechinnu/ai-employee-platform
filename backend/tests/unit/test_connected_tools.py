"""Google and Microsoft tools, against fake APIs.

What matters here is our side: the grant reaches the request and no
further, failures come back as sentences the model can act on, and a
dry run never touches the outside world.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.agent.tools import Grant, ToolContext, registry

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], list[httpx.Request]]:
    import app.agent.tools.packs._http as http_mod

    def install(handler: Handler) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(
            http_mod,
            "_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(recording)),
        )
        return seen

    return install


def _ctx(kind: str = "google", **kwargs: Any) -> ToolContext:
    return ToolContext(
        owner_id=uuid.uuid4(),
        grants={kind: Grant(credential="tok-123", config={"account": "ops@acme.com"})},
        **kwargs,
    )


async def _run(name: str, ctx: ToolContext, args: dict[str, Any]) -> Any:
    tool = registry.get(name)
    assert tool is not None, name
    return await tool().execute(ctx, args)


def test_every_connected_tool_is_registered_with_a_side_effect() -> None:
    google = [t for t in registry.all() if t.requires_connection == "google"]
    microsoft = [t for t in registry.all() if t.requires_connection == "microsoft"]
    # Eight for mail, calendar and Drive, and four for Sheets.
    assert len(google) == 12
    assert len(microsoft) == 8
    sends = {t.name: t.side_effect.value for t in google + microsoft if "send" in t.name}
    assert sends == {"gmail_send": "destructive", "outlook_send": "destructive"}


async def test_a_tool_without_a_connection_says_how_to_fix_it() -> None:
    result = await _run("gmail_search", ToolContext(owner_id=uuid.uuid4()), {"query": "x"})
    assert not result.ok
    assert result.error_class == "not_connected"
    assert "Settings > Connections" in (result.message or "")


async def test_gmail_search_uses_the_grant(fake_api: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        return httpx.Response(
            200,
            json={
                "id": "m1",
                "snippet": "Invoice attached",
                "labelIds": ["UNREAD"],
                "payload": {
                    "headers": [
                        {"name": "From", "value": "alice@example.com"},
                        {"name": "Subject", "value": "Invoice"},
                    ]
                },
            },
        )

    seen = fake_api(handler)
    result = await _run("gmail_search", _ctx(), {"query": "invoice"})

    assert result.ok, result.message
    assert result.data["messages"][0]["subject"] == "Invoice"
    assert result.data["messages"][0]["unread"] is True
    assert all(r.headers["Authorization"] == "Bearer tok-123" for r in seen)


async def test_gmail_read_prefers_plain_text(fake_api: Any) -> None:
    def encode(text: str) -> str:
        return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")

    fake_api(
        lambda r: httpx.Response(
            200,
            json={
                "id": "m1",
                "payload": {
                    "headers": [{"name": "Subject", "value": "Hi"}],
                    "parts": [
                        {"mimeType": "text/html", "body": {"data": encode("<b>rich</b>")}},
                        {"mimeType": "text/plain", "body": {"data": encode("plain body")}},
                    ],
                },
            },
        )
    )
    result = await _run("gmail_read", _ctx(), {"message_id": "m1"})
    assert result.data["body"] == "plain body"


async def test_a_dry_run_send_touches_nothing(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(500))
    result = await _run(
        "outlook_send",
        _ctx("microsoft", dry_run=True),
        {"to": ["bob@example.com"], "subject": "Hello", "body": "Hi Bob"},
    )
    assert result.ok and result.data["dry_run"] is True
    assert seen == []


async def test_an_expired_token_reads_as_reconnect(fake_api: Any) -> None:
    fake_api(lambda r: httpx.Response(401, json={"error": "invalid_token"}))
    result = await _run("outlook_search", _ctx("microsoft"), {})
    assert result.error_class == "auth_expired"
    assert "reconnect" in (result.message or "")


async def test_drive_search_escapes_quotes(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200, json={"files": []}))
    await _run("google_drive_search", _ctx(), {"query": "Q3 'final' plan"})
    q = seen[0].url.params["q"]
    assert "\\'final\\'" in q
    assert q.endswith("trashed = false")


async def test_calendar_create_rejects_an_end_before_the_start(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200, json={}))
    result = await _run(
        "google_calendar_create",
        _ctx(),
        {"title": "Sync", "start": "2026-10-14T15:00:00Z", "end": "2026-10-14T14:00:00Z"},
    )
    assert result.error_class == "invalid_arguments"
    assert seen == []


async def test_onedrive_reads_a_word_document(fake_api: Any) -> None:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            "<w:document><w:body><w:p><w:r><w:t>Hello plan</w:t></w:r></w:p></w:body></w:document>",
        )
    docx = buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/content"):
            return httpx.Response(200, content=docx)
        return httpx.Response(200, json={"name": "plan.docx", "size": len(docx), "file": {}})

    fake_api(handler)
    result = await _run("onedrive_read", _ctx("microsoft"), {"file_id": "abc"})
    assert result.ok, result.message
    assert "Hello plan" in result.data["text"]


@pytest.mark.parametrize(
    ("tool", "kind", "start_param"),
    [
        ("google_calendar_list", "google", "timeMin"),
        ("outlook_calendar_list", "microsoft", "startDateTime"),
    ],
)
async def test_a_calendar_can_look_back_at_past_events(
    fake_api: Any, tool: str, kind: str, start_param: str
) -> None:
    from datetime import UTC, datetime, timedelta

    seen = fake_api(lambda request: httpx.Response(200, json={"items": [], "value": []}))
    result = await _run(tool, _ctx(kind), {"days_back": 7, "days_ahead": 0})

    assert result.ok, result.message
    start = datetime.fromisoformat(seen[0].url.params[start_param].replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    assert datetime.now(UTC) - start > timedelta(days=6)
