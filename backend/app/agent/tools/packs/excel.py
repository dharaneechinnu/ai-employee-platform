"""Excel workbooks in OneDrive, through the Microsoft Graph workbook API.

The Microsoft side of Google Sheets: read a sheet, add rows to the
bottom, change existing cells. Like the Sheets tools, nothing here can
delete a sheet, remove rows or blank cells. Reading needs OneDrive's
read permission; adding and changing need its edit permission
(`Files.ReadWrite.All`), which a person chooses to grant when they connect.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, Field

from app.agent.tools.base import SideEffect, ToolContext, ToolResult
from app.agent.tools.packs._http import ApiTool, request
from app.agent.tools.packs.microsoft import GRAPH
from app.agent.tools.registry import register

MAX_ROWS_PER_CALL = 200
MAX_READ_ROWS = 2000
Cell = str | int | float | bool | None

_CELL = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")


def _column(n: int) -> str:
    """1 -> A, 27 -> AA."""
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _column_number(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _book(file_id: str) -> str:
    return f"{GRAPH}/drive/items/{quote(file_id, safe='')}/workbook"


def _sheet(file_id: str, sheet: str) -> str:
    return f"{_book(file_id)}/worksheets/{quote(sheet, safe='')}"


def _rectangle(rows: list[list[Cell]]) -> list[list[Cell]]:
    """Graph wants every row the same width: pad the short ones."""
    width = max(len(r) for r in rows)
    return [list(r) + [""] * (width - len(r)) for r in rows]


async def _first_sheet(ctx: ToolContext, file_id: str) -> str:
    sheets = await request(ctx, "GET", f"{_book(file_id)}/worksheets", params={"$select": "name"})
    names = [str(s["name"]) for s in sheets.get("value", [])]
    if not names:
        raise ValueError("That workbook has no sheets.")
    return names[0]


async def _used(ctx: ToolContext, file_id: str, sheet: str) -> dict[str, Any]:
    used: dict[str, Any] = await request(
        ctx,
        "GET",
        f"{_sheet(file_id, sheet)}/usedRange(valuesOnly=true)",
        params={"$select": "address,values,rowCount"},
    )
    return used


def _last_row(used: dict[str, Any]) -> int:
    """The last row with anything in it, 0 for an empty sheet."""
    values = used.get("values") or []
    if not any(str(c).strip() for row in values for c in row):
        return 0
    address = str(used.get("address", "")).split("!")[-1]
    end = address.split(":")[-1]
    match = re.match(r"^\$?[A-Z]+\$?(\d+)$", end)
    return int(match.group(1)) if match else len(values)


# ------------------------------------------------------------------ read


class ExcelReadArgs(BaseModel):
    file_id: str = Field(
        min_length=1, max_length=500, description="The id onedrive_search returned"
    )
    sheet: str | None = Field(default=None, max_length=100, description="Leave out for the first")


@register
class ExcelRead(ApiTool):
    name = "excel_read"
    pack = "excel"
    description = (
        "Read an Excel workbook in OneDrive: the sheet names and the rows of one sheet. "
        "Use it before adding rows, to see what is already there."
    )
    args_model = ExcelReadArgs
    side_effect = SideEffect.READ
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: ExcelReadArgs) -> ToolResult:
        sheets = await request(
            ctx, "GET", f"{_book(args.file_id)}/worksheets", params={"$select": "name"}
        )
        names = [s["name"] for s in sheets.get("value", [])]
        if not names:
            return ToolResult.failure("not_found", "That workbook has no sheets.")
        sheet = args.sheet or names[0]
        if sheet not in names:
            return ToolResult.failure(
                "not_found",
                f"There is no sheet called '{sheet}'. The sheets are: {', '.join(names)}.",
            )
        used = await _used(ctx, args.file_id, sheet)
        rows = used.get("values") or []
        if _last_row(used) == 0:
            rows = []
        return ToolResult.success(
            {
                "sheets": names,
                "sheet": sheet,
                "range": used.get("address"),
                "rows": rows[:MAX_READ_ROWS],
                "row_count": len(rows),
                "cut": len(rows) > MAX_READ_ROWS,
            }
        )


# ------------------------------------------------------------------ append


class ExcelAppendArgs(BaseModel):
    file_id: str = Field(
        min_length=1, max_length=500, description="The id onedrive_search returned"
    )
    sheet: str | None = Field(default=None, max_length=100, description="Leave out for the first")
    rows: list[list[Cell]] = Field(
        min_length=1,
        max_length=MAX_ROWS_PER_CALL,
        description="New rows, each a list of cell values in column order",
    )


@register
class ExcelAppendRows(ApiTool):
    name = "excel_append_rows"
    pack = "excel"
    description = (
        "Add new rows below the last filled row of a sheet in an Excel workbook in OneDrive. "
        "Existing rows are never changed. Check with excel_read first so you do not add "
        "duplicates."
    )
    args_model = ExcelAppendArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: ExcelAppendArgs) -> ToolResult:
        rows = _rectangle(args.rows)
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_append": len(rows)})
        try:
            sheet = args.sheet or await _first_sheet(ctx, args.file_id)
        except ValueError as exc:
            return ToolResult.failure("not_found", str(exc))
        start = _last_row(await _used(ctx, args.file_id, sheet)) + 1
        address = f"A{start}:{_column(len(rows[0]))}{start + len(rows) - 1}"
        done = await request(
            ctx,
            "PATCH",
            f"{_sheet(args.file_id, sheet)}/range(address='{address}')",
            json={"values": rows},
        )
        return ToolResult.success(
            {"appended_rows": len(rows), "sheet": sheet, "range": done.get("address", address)}
        )


# ------------------------------------------------------------------ update


class ExcelUpdateArgs(BaseModel):
    file_id: str = Field(
        min_length=1, max_length=500, description="The id onedrive_search returned"
    )
    sheet: str | None = Field(default=None, max_length=100, description="Leave out for the first")
    cell: str = Field(
        min_length=2, max_length=10, description="Where the first value goes, such as D7"
    )
    values: list[list[Cell]] = Field(
        min_length=1,
        max_length=MAX_ROWS_PER_CALL,
        description="The new cell values, one list per row, starting at that cell",
    )


@register
class ExcelUpdateCells(ApiTool):
    name = "excel_update_cells"
    pack = "excel"
    description = (
        "Change the values of existing cells in an Excel workbook in OneDrive, for example "
        "to update a status or a date. It cannot blank cells or remove rows."
    )
    args_model = ExcelUpdateArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "microsoft"

    async def call(self, ctx: ToolContext, args: ExcelUpdateArgs) -> ToolResult:
        match = _CELL.match(args.cell.strip().upper().replace("$", ""))
        if not match:
            return ToolResult.failure("invalid_arguments", "cell must look like D7.")
        values = _rectangle(args.values)
        if not any(str(c).strip() for row in values for c in row if c is not None):
            return ToolResult.failure(
                "not_allowed", "That would only blank cells. Clearing cells is not allowed."
            )
        letters, row = match.group(1), int(match.group(2))
        end_col = _column(_column_number(letters) + len(values[0]) - 1)
        address = f"{letters}{row}:{end_col}{row + len(values) - 1}"
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_update": address})
        try:
            sheet = args.sheet or await _first_sheet(ctx, args.file_id)
        except ValueError as exc:
            return ToolResult.failure("not_found", str(exc))
        done = await request(
            ctx,
            "PATCH",
            f"{_sheet(args.file_id, sheet)}/range(address='{address}')",
            json={"values": values},
        )
        return ToolResult.success(
            {
                "updated_cells": len(values) * len(values[0]),
                "sheet": sheet,
                "range": done.get("address", address),
            }
        )
