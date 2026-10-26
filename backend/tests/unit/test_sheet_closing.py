"""The closing block of a run that used Google Sheets.

It is built from what the sheet tools really did, so the person always
gets the sheet's link and an honest count, even if the AI forgets either.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from app.agent.tools import Grant, ToolContext, registry
from app.agent.tools.sheet_log import KEY, closing

SHEET = "1AbCdEfGhIjKlMnOpQrStUvWxYz"
LINK = f"https://docs.google.com/spreadsheets/d/{SHEET}/edit"


@pytest.fixture
def fake_google(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent.tools.packs._http as http_mod

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url.endswith("/spreadsheets"):
            return httpx.Response(200, json={"spreadsheetId": SHEET})
        if ":append" in url:
            return httpx.Response(
                200, json={"updates": {"updatedRows": 3, "updatedRange": "A2:F4"}}
            )
        if request.method == "PUT":
            return httpx.Response(200, json={"updatedCells": 2, "updatedRange": "D7:E7"})
        if "/values/" in url:
            return httpx.Response(200, json={"values": [["Name"]]})
        return httpx.Response(200, json={"sheets": [{"properties": {"title": "Events"}}]})

    monkeypatch.setattr(
        http_mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def _ctx(log: list[dict[str, Any]]) -> ToolContext:
    return ToolContext(
        owner_id=uuid.uuid4(),
        grants={"google": Grant(credential="tok")},
        config={KEY: log, "allowed_sheet_ids": []},
    )


async def _run(name: str, ctx: ToolContext, args: dict[str, Any]) -> Any:
    tool = registry.get(name)
    assert tool is not None
    return await tool().execute(ctx, args)


async def test_a_first_night_reports_the_new_sheet_the_rows_and_the_link(
    fake_google: None,
) -> None:
    log: list[dict[str, Any]] = []
    ctx = _ctx(log)

    made = await _run("sheets_create", ctx, {"title": "Developer Meetups", "tabs": ["Events"]})
    assert made.ok
    added = await _run(
        "sheets_append_rows",
        ctx,
        {"spreadsheet": LINK, "tab": "Events", "rows": [["a"], ["b"], ["c"]]},
    )
    assert added.ok

    text = closing(log) or ""
    assert "created the sheet “Developer Meetups”" in text
    assert "added 3 rows to Events" in text
    assert f"Open the sheet: {LINK}" in text


async def test_a_run_that_only_looked_says_nothing_new_was_added(fake_google: None) -> None:
    log: list[dict[str, Any]] = []
    ctx = _ctx(log)
    ctx.config["allowed_sheet_ids"] = [SHEET]  # type: ignore[index]

    assert (await _run("sheets_read", ctx, {"spreadsheet": SHEET})).ok

    text = closing(log) or ""
    assert "nothing new to add" in text and LINK in text


async def test_changed_cells_are_counted(fake_google: None) -> None:
    log: list[dict[str, Any]] = []
    ctx = _ctx(log)
    ctx.config["allowed_sheet_ids"] = [SHEET]  # type: ignore[index]

    await _run(
        "sheets_update_cells",
        ctx,
        {"spreadsheet": SHEET, "tab": "Events", "cells": "D7", "values": [["2026-11-09", "x"]]},
    )
    assert "changed 2 cells" in (closing(log) or "")


async def test_a_dry_run_and_a_refused_write_leave_no_record(fake_google: None) -> None:
    log: list[dict[str, Any]] = []
    ctx = _ctx(log)
    ctx.dry_run = True
    await _run("sheets_create", ctx, {"title": "x", "tabs": ["Events"]})
    assert log == []

    ctx = _ctx(log)  # the fence has no sheet in it
    refused = await _run(
        "sheets_append_rows", ctx, {"spreadsheet": SHEET, "tab": "Events", "rows": [["a"]]}
    )
    assert not refused.ok and log == []


def test_a_refused_write_is_named_with_its_reason() -> None:
    text = closing(
        [], blocked=[("sheets_append_rows", "it needs approval, and no one is there to give it")]
    )
    assert text is not None
    assert "Not saved" in text and "sheets_append_rows" in text and "Permissions" in text


def test_a_run_that_never_touched_sheets_adds_nothing() -> None:
    assert closing([], blocked=[("gmail_send", "blocked")]) is None
    assert closing([]) is None


def test_two_sheets_each_get_their_own_link() -> None:
    log = [
        {"action": "added", "sheet_id": "AAA", "tab": "T", "rows": 1},
        {"action": "added", "sheet_id": "BBB", "tab": "T", "rows": 2},
    ]
    text = closing(log) or ""
    assert "d/AAA/edit" in text and "d/BBB/edit" in text
