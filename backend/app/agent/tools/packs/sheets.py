"""Google Sheets: read a sheet, add rows, change cells.

Three tools and no more. There is deliberately no tool that deletes a
row, a tab or a spreadsheet, and `sheets_update_cells` refuses a write
that would only blank cells, so an agent that goes wrong can overwrite
a cell but cannot empty a sheet.

An agent can be limited to named spreadsheets (`allowed_sheet_ids` in
its context). That limit is checked here, in the tool, because it must
hold whatever the model is persuaded to try: a web page it read cannot
talk it into writing somewhere else.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, Field

from app.agent.tools import sheet_log
from app.agent.tools.base import SideEffect, ToolContext, ToolResult
from app.agent.tools.packs._http import ApiTool, request
from app.agent.tools.registry import register

SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
MAX_ROWS_PER_CALL = 200
MAX_READ_ROWS = 2000

_ID_IN_URL = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
_BARE_ID = re.compile(r"^[A-Za-z0-9_-]{20,}$")


def spreadsheet_id(value: str) -> str | None:
    """The id from a pasted address, or the id itself."""
    value = value.strip()
    if match := _ID_IN_URL.search(value):
        return match.group(1)
    return value if _BARE_ID.match(value) else None


def _refuse(ctx: ToolContext, value: str) -> tuple[str | None, ToolResult | None]:
    """The spreadsheet id, or a failure the model can read."""
    sheet_id = spreadsheet_id(value)
    if sheet_id is None:
        return None, ToolResult.failure(
            "invalid_spreadsheet", "Give the spreadsheet's full address or its id."
        )
    config = ctx.config or {}
    # The key being present is the limit, even when the list is empty: an
    # agent that has no spreadsheet yet may write nowhere until it makes one.
    if "allowed_sheet_ids" in config:
        allowed = [str(i) for i in config["allowed_sheet_ids"]]
        if sheet_id not in allowed:
            return None, ToolResult.failure(
                "not_allowed",
                "This agent may only use its own spreadsheet. Do not try another one.",
            )
    return sheet_id, None


def _grid(values: list[list[Any]]) -> list[list[str]]:
    return [["" if cell is None else str(cell) for cell in row] for row in values]


def _tab_range(tab: str, cells: str = "") -> str:
    """A1 notation with the tab name quoted, then URL-encoded."""
    name = "'" + tab.replace("'", "''") + "'"
    return quote(f"{name}!{cells}" if cells else name, safe="")


# ------------------------------------------------------------------ create


class SheetsCreateArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200, description="The spreadsheet's name")
    tabs: list[str] = Field(
        default_factory=lambda: ["Sheet1"],
        min_length=1,
        max_length=10,
        description="Tab names, for example ['Events', 'Run Log']",
    )
    headers: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Optional first row for a tab: {'Events': ['Name', 'Date', 'Link']}",
    )


@register
class SheetsCreate(ApiTool):
    name = "sheets_create"
    pack = "sheets"
    description = (
        "Create a new Google Sheet with the tabs and header rows you give. Only do this if "
        "you have not been given a spreadsheet already. Once created, you may write to it "
        "with sheets_append_rows and sheets_update_cells, and it stays yours for later runs."
    )
    args_model = SheetsCreateArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: SheetsCreateArgs) -> ToolResult:
        tabs = list(dict.fromkeys(t.strip() for t in args.tabs if t.strip()))
        if not tabs:
            return ToolResult.failure("invalid_arguments", "Give at least one tab name.")
        unknown = [t for t in args.headers if t not in tabs]
        if unknown:
            return ToolResult.failure(
                "invalid_arguments", f"Headers were given for tabs that do not exist: {unknown}."
            )
        if ctx.dry_run:
            return ToolResult.success(
                {"dry_run": True, "would_create": {"title": args.title, "tabs": tabs}}
            )
        made = await request(
            ctx,
            "POST",
            SHEETS,
            json={
                "properties": {"title": args.title},
                "sheets": [{"properties": {"title": t}} for t in tabs],
            },
        )
        new_id = str(made.get("spreadsheetId", ""))
        if not new_id:
            return ToolResult.failure("api_error", "Google did not return the new spreadsheet.")
        if args.headers:
            await request(
                ctx,
                "POST",
                f"{SHEETS}/{new_id}/values:batchUpdate",
                json={
                    "valueInputOption": "RAW",
                    "data": [
                        {"range": _a1(tab, "A1"), "values": [_grid([row])[0]]}
                        for tab, row in args.headers.items()
                    ],
                },
            )
        await _keep_for_the_agent(ctx, new_id)
        sheet_log.note(ctx.config, action="created", sheet_id=new_id, title=args.title)
        return ToolResult.success(
            {
                "spreadsheet_id": new_id,
                "url": made.get("spreadsheetUrl")
                or f"https://docs.google.com/spreadsheets/d/{new_id}/edit",
                "tabs": tabs,
            }
        )


def _a1(tab: str, cells: str) -> str:
    return "'" + tab.replace("'", "''") + "'!" + cells


async def _keep_for_the_agent(ctx: ToolContext, sheet_id: str) -> None:
    """A spreadsheet an agent made is one it may keep using: add it to the
    run's limit now, and to the agent itself so tomorrow's run finds it."""
    config = ctx.config or {}
    allowed = config.get("allowed_sheet_ids")
    if isinstance(allowed, list) and sheet_id not in allowed:
        allowed.append(sheet_id)
    agent_id, session = config.get("_agent_id"), config.get("_session")
    if agent_id is None or session is None:
        return
    from app.db.models.agent import Agent

    agent = await session.get(Agent, agent_id)
    if agent is not None:
        ids = [str(i) for i in (agent.scope or {}).get("sheet_ids", [])]
        if sheet_id not in ids:
            # A new dict, so the change is noticed and saved.
            agent.scope = {**(agent.scope or {}), "sheet_ids": [*ids, sheet_id]}
            await session.flush()


# ------------------------------------------------------------------ read


class SheetsReadArgs(BaseModel):
    spreadsheet: str = Field(description="The spreadsheet's full address, or its id")
    tab: str | None = Field(default=None, description="Tab name. Leave out to read the first tab.")
    cells: str | None = Field(
        default=None, description="Optional range such as A1:M500. Leave out for the whole tab."
    )


@register
class SheetsRead(ApiTool):
    name = "sheets_read"
    pack = "sheets"
    description = (
        "Read a Google Sheet: the tab names and the rows of one tab. Use it before "
        "adding rows, to see what is already there."
    )
    args_model = SheetsReadArgs
    side_effect = SideEffect.READ
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: SheetsReadArgs) -> ToolResult:
        sheet_id, refusal = _refuse(ctx, args.spreadsheet)
        if refusal:
            return refusal
        meta = await request(
            ctx, "GET", f"{SHEETS}/{sheet_id}", params={"fields": "sheets.properties.title"}
        )
        tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
        tab = args.tab or (tabs[0] if tabs else None)
        if tab is None:
            return ToolResult.success({"tabs": [], "rows": []})
        if tabs and tab not in tabs:
            return ToolResult.failure(
                "tab_not_found", f"There is no tab called '{tab}'. Tabs: {', '.join(tabs)}."
            )
        data = await request(
            ctx, "GET", f"{SHEETS}/{sheet_id}/values/{_tab_range(tab, args.cells or '')}"
        )
        rows = data.get("values", [])
        sheet_log.note(ctx.config, action="read", sheet_id=sheet_id)
        truncated = len(rows) > MAX_READ_ROWS
        return ToolResult.success(
            {
                "tabs": tabs,
                "tab": tab,
                "row_count": len(rows),
                "rows": rows[:MAX_READ_ROWS],
                "truncated": truncated,
            }
        )


# ------------------------------------------------------------------ append


class SheetsAppendArgs(BaseModel):
    spreadsheet: str = Field(description="The spreadsheet's full address, or its id")
    tab: str = Field(description="The tab to add rows to, for example 'Events'")
    rows: list[list[str]] = Field(
        min_length=1,
        max_length=MAX_ROWS_PER_CALL,
        description="New rows, each a list of cell values in column order",
    )


@register
class SheetsAppendRows(ApiTool):
    name = "sheets_append_rows"
    pack = "sheets"
    description = (
        "Add new rows to the bottom of a tab in a Google Sheet. Existing rows are never "
        "changed or removed. Check with sheets_read first so you do not add duplicates."
    )
    args_model = SheetsAppendArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: SheetsAppendArgs) -> ToolResult:
        sheet_id, refusal = _refuse(ctx, args.spreadsheet)
        if refusal:
            return refusal
        rows = _grid(args.rows)
        if ctx.dry_run:
            return ToolResult.success(
                {"dry_run": True, "would_append": {"tab": args.tab, "rows": len(rows)}}
            )
        done = await request(
            ctx,
            "POST",
            f"{SHEETS}/{sheet_id}/values/{_tab_range(args.tab, 'A1')}:append",
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json={"values": rows},
        )
        updates = done.get("updates", {})
        sheet_log.note(
            ctx.config,
            action="added",
            sheet_id=sheet_id,
            tab=args.tab,
            rows=int(updates.get("updatedRows", len(rows))),
        )
        return ToolResult.success(
            {
                "appended_rows": updates.get("updatedRows", len(rows)),
                "range": updates.get("updatedRange"),
            }
        )


# ------------------------------------------------------------------ update


class SheetsUpdateArgs(BaseModel):
    spreadsheet: str = Field(description="The spreadsheet's full address, or its id")
    tab: str = Field(description="The tab to change")
    cells: str = Field(description="Where the first value goes, or a range, such as D7 or D7:M7")
    values: list[list[str]] = Field(
        min_length=1,
        max_length=MAX_ROWS_PER_CALL,
        description="The new cell values, one list per row",
    )


@register
class SheetsUpdateCells(ApiTool):
    name = "sheets_update_cells"
    pack = "sheets"
    description = (
        "Change the values of existing cells, for example to update an event's date. "
        "It cannot blank cells or remove rows."
    )
    args_model = SheetsUpdateArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "google"

    async def call(self, ctx: ToolContext, args: SheetsUpdateArgs) -> ToolResult:
        sheet_id, refusal = _refuse(ctx, args.spreadsheet)
        if refusal:
            return refusal
        values = _grid(args.values)
        if not any(cell.strip() for row in values for cell in row):
            return ToolResult.failure(
                "not_allowed", "That would only blank cells. Clearing cells is not allowed."
            )
        if ctx.dry_run:
            return ToolResult.success(
                {"dry_run": True, "would_update": {"tab": args.tab, "cells": args.cells}}
            )
        done = await request(
            ctx,
            "PUT",
            f"{SHEETS}/{sheet_id}/values/{_tab_range(args.tab, args.cells)}",
            params={"valueInputOption": "USER_ENTERED"},
            json={"values": values},
        )
        sheet_log.note(
            ctx.config,
            action="updated",
            sheet_id=sheet_id,
            cells=int(done.get("updatedCells") or sum(len(r) for r in values)),
        )
        return ToolResult.success(
            {"updated_cells": done.get("updatedCells"), "range": done.get("updatedRange")}
        )


def sheet_ids_in(scope: dict[str, object] | None) -> list[str]:
    """The spreadsheets an agent's scope names, as a clean list."""
    ids = (scope or {}).get("sheet_ids")
    return [str(i) for i in ids] if isinstance(ids, list) else []
