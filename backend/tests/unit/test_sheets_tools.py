"""Google Sheets tools, the clock and web search, against fake APIs.

What matters is our side: an agent limited to one spreadsheet stays
there whatever it is told, no tool can empty a sheet, a dry run touches
nothing, and a missing search key says so plainly.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.agent.tools import Grant, ToolContext, registry
from app.agent.tools.packs.sheets import spreadsheet_id

Handler = Callable[[httpx.Request], httpx.Response]

SHEET = "1duLbxa70UPyCCa2y33F-VpOGPWH4XLxAbt-U3Ylu1KI"
OTHER = "9zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"


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


def _ctx(**config: Any) -> ToolContext:
    return ToolContext(
        owner_id=uuid.uuid4(),
        grants={"google": Grant(credential="tok-123", config={"account": "ops@acme.com"})},
        config=config or None,
        dry_run=bool(config.pop("dry_run", False)),
    )


async def _run(name: str, ctx: ToolContext, args: dict[str, Any]) -> Any:
    tool = registry.get(name)
    assert tool is not None, name
    return await tool().execute(ctx, args)


def test_a_spreadsheet_can_be_given_as_its_address_or_its_id() -> None:
    url = f"https://docs.google.com/spreadsheets/d/{SHEET}/edit#gid=0"
    assert spreadsheet_id(url) == SHEET
    assert spreadsheet_id(SHEET) == SHEET
    assert spreadsheet_id("not a sheet") is None
    assert spreadsheet_id("https://example.com/evil") is None


async def test_reading_a_sheet_lists_its_tabs_and_rows(fake_api: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/spreadsheets/{SHEET}"):
            return httpx.Response(
                200,
                json={
                    "sheets": [
                        {"properties": {"title": "Events"}},
                        {"properties": {"title": "Log"}},
                    ]
                },
            )
        return httpx.Response(
            200, json={"values": [["Name", "Date"], ["Chennai React", "2026-11-02"]]}
        )

    seen = fake_api(handler)
    result = await _run("sheets_read", _ctx(), {"spreadsheet": SHEET})

    assert result.ok, result.message
    assert result.data["tabs"] == ["Events", "Log"]
    assert result.data["tab"] == "Events"
    assert result.data["rows"][1] == ["Chennai React", "2026-11-02"]
    assert all(r.headers["Authorization"] == "Bearer tok-123" for r in seen)


async def test_reading_a_tab_that_does_not_exist_names_the_real_ones(fake_api: Any) -> None:
    fake_api(lambda r: httpx.Response(200, json={"sheets": [{"properties": {"title": "Events"}}]}))
    result = await _run("sheets_read", _ctx(), {"spreadsheet": SHEET, "tab": "Nope"})
    assert not result.ok
    assert result.error_class == "tab_not_found"
    assert "Events" in (result.message or "")


async def test_appending_adds_rows_at_the_bottom(fake_api: Any) -> None:
    seen = fake_api(
        lambda r: httpx.Response(
            200, json={"updates": {"updatedRows": 2, "updatedRange": "Events!A5:C6"}}
        )
    )
    result = await _run(
        "sheets_append_rows",
        _ctx(),
        {"spreadsheet": SHEET, "tab": "Events", "rows": [["a", "b", "c"], ["d", "e", "f"]]},
    )
    assert result.ok, result.message
    assert result.data["appended_rows"] == 2
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path.endswith(":append")
    assert request.url.params["insertDataOption"] == "INSERT_ROWS"


async def test_updating_changes_cells(fake_api: Any) -> None:
    seen = fake_api(
        lambda r: httpx.Response(200, json={"updatedCells": 1, "updatedRange": "Events!B3"})
    )
    result = await _run(
        "sheets_update_cells",
        _ctx(),
        {"spreadsheet": SHEET, "tab": "Events", "cells": "B3", "values": [["2026-11-09"]]},
    )
    assert result.ok, result.message
    assert seen[0].method == "PUT"


async def test_an_update_that_would_only_blank_cells_is_refused(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200, json={}))
    result = await _run(
        "sheets_update_cells",
        _ctx(),
        {"spreadsheet": SHEET, "tab": "Events", "cells": "A2:C9", "values": [["", ""], [" ", ""]]},
    )
    assert not result.ok
    assert result.error_class == "not_allowed"
    assert seen == []


async def test_an_agent_limited_to_one_sheet_cannot_touch_another(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200, json={}))
    ctx = _ctx(allowed_sheet_ids=[SHEET])
    for name, args in (
        ("sheets_read", {"spreadsheet": OTHER}),
        ("sheets_append_rows", {"spreadsheet": OTHER, "tab": "Events", "rows": [["x"]]}),
        (
            "sheets_update_cells",
            {"spreadsheet": OTHER, "tab": "Events", "cells": "A1", "values": [["x"]]},
        ),
    ):
        result = await _run(name, ctx, args)
        assert not result.ok and result.error_class == "not_allowed", name
    assert seen == []


async def test_a_dry_run_writes_nothing(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200, json={}))
    ctx = ToolContext(
        owner_id=uuid.uuid4(),
        grants={"google": Grant(credential="tok-123")},
        dry_run=True,
    )
    result = await _run(
        "sheets_append_rows", ctx, {"spreadsheet": SHEET, "tab": "Events", "rows": [["x"]]}
    )
    assert result.ok and result.data["dry_run"] is True
    assert seen == []


async def test_a_403_says_the_connection_may_need_more_permission(fake_api: Any) -> None:
    fake_api(lambda r: httpx.Response(403, json={"error": "insufficient"}))
    result = await _run("sheets_read", _ctx(), {"spreadsheet": SHEET})
    assert not result.ok and result.error_class == "forbidden"
    assert "reconnect" in (result.message or "").lower()


def test_there_is_no_tool_that_deletes_anything_in_a_sheet() -> None:
    names = {t.name for t in registry.all() if t.pack == "sheets"}
    assert names == {"sheets_read", "sheets_create", "sheets_append_rows", "sheets_update_cells"}


# ------------------------------------------------------------------ clock


async def test_the_clock_gives_todays_date_in_the_asked_zone() -> None:
    result = await _run(
        "current_time", ToolContext(owner_id=uuid.uuid4()), {"timezone": "Asia/Kolkata"}
    )
    assert result.ok
    assert len(result.data["date"]) == 10 and result.data["timezone"] == "Asia/Kolkata"


async def test_the_clock_refuses_a_made_up_zone() -> None:
    result = await _run(
        "current_time", ToolContext(owner_id=uuid.uuid4()), {"timezone": "Mars/Base"}
    )
    assert not result.ok and result.error_class == "invalid_timezone"


# ------------------------------------------------------------------ search


async def test_search_without_a_key_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "brave_api_key", None)
    result = await _run(
        "web_search", ToolContext(owner_id=uuid.uuid4()), {"query": "chennai meetup"}
    )
    assert not result.ok and result.error_class == "not_configured"


async def test_search_returns_titles_addresses_and_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.tools.packs import search
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "brave_api_key", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "k"
        assert request.url.params["freshness"] == "pw"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Chennai React",
                            "url": "https://lu.ma/x",
                            "description": "Meetup",
                        }
                    ]
                }
            },
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        search.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler))
    )
    result = await _run(
        "web_search",
        ToolContext(owner_id=uuid.uuid4()),
        {"query": "chennai meetup", "freshness": "week"},
    )
    assert result.ok, result.message
    assert result.data["results"][0]["url"] == "https://lu.ma/x"


# ------------------------------------------------------------------ create


async def test_creating_a_sheet_makes_tabs_and_header_rows(fake_api: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("values:batchUpdate"):
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"spreadsheetId": SHEET, "spreadsheetUrl": "https://x/y"})

    seen = fake_api(handler)
    result = await _run(
        "sheets_create",
        _ctx(),
        {
            "title": "Chennai Developer Events",
            "tabs": ["Events", "Run Log"],
            "headers": {"Events": ["Name", "Date", "Link"]},
        },
    )
    assert result.ok, result.message
    assert result.data["spreadsheet_id"] == SHEET and result.data["tabs"] == ["Events", "Run Log"]
    assert [r.method for r in seen] == ["POST", "POST"]
    assert b"Chennai Developer Events" in seen[0].content
    assert b"Name" in seen[1].content


async def test_headers_for_a_tab_that_does_not_exist_are_refused(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200, json={}))
    result = await _run(
        "sheets_create", _ctx(), {"title": "T", "tabs": ["A"], "headers": {"B": ["x"]}}
    )
    assert not result.ok and result.error_class == "invalid_arguments"
    assert seen == []


async def test_a_dry_run_creates_nothing(fake_api: Any) -> None:
    seen = fake_api(lambda r: httpx.Response(200, json={}))
    ctx = ToolContext(owner_id=uuid.uuid4(), grants={"google": Grant(credential="t")}, dry_run=True)
    result = await _run("sheets_create", ctx, {"title": "T"})
    assert result.ok and result.data["dry_run"] is True
    assert seen == []


async def test_a_sheet_the_agent_creates_joins_the_ones_it_may_use(fake_api: Any) -> None:
    fake_api(lambda r: httpx.Response(200, json={"spreadsheetId": SHEET}))
    allowed: list[str] = []
    ctx = _ctx(allowed_sheet_ids=allowed)
    assert (await _run("sheets_create", ctx, {"title": "T"})).ok
    assert allowed == [SHEET]


async def test_an_agent_with_no_sheet_yet_may_write_nowhere(fake_api: Any) -> None:
    """The limit is the list existing, even empty, so it must make one first."""
    seen = fake_api(lambda r: httpx.Response(200, json={}))
    result = await _run(
        "sheets_append_rows",
        _ctx(allowed_sheet_ids=[]),
        {"spreadsheet": SHEET, "tab": "Events", "rows": [["x"]]},
    )
    assert not result.ok and result.error_class == "not_allowed"
    assert seen == []
