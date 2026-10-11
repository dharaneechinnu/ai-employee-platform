"""Read-only SQL tools.

Read-only is enforced three ways, and only one of them actually
protects the customer:

1. A read-only database user. The database itself refuses writes.
   **This is the real guard.**
2. Statement inspection, which rejects anything that is not a SELECT.
3. A row cap and a statement timeout.

Guards 2 and 3 exist for better error messages and to stop one heavy
query freezing a live database. Never rely on inspecting query text
alone — it is trivially defeated, and anyone who treats it as the
protection has misunderstood where the boundary is.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import register

MAX_ROWS = 1_000
STATEMENT_TIMEOUT_MS = 10_000

# Anything that is not a plain SELECT or WITH ... SELECT.
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|CALL|DO)\b",
    re.IGNORECASE,
)


def _looks_read_only(sql: str) -> tuple[bool, str]:
    stripped = sql.strip().rstrip(";")

    if ";" in stripped:
        # One statement per call: a trailing statement is the classic
        # way to smuggle a write past a prefix check.
        return False, "Only one statement is allowed per query."
    if not re.match(r"^\s*(SELECT|WITH)\b", stripped, re.IGNORECASE):
        return False, "Only SELECT queries are allowed."
    if _FORBIDDEN.search(stripped):
        return False, "That query contains a statement that changes data."
    return True, ""


def _engine(ctx: ToolContext):  # type: ignore[no-untyped-def]
    config = ctx.config or {}
    host = config.get("host", "localhost")
    port = config.get("port", 5432)
    database = config["database"]
    username = config["username"]
    return create_async_engine(
        f"postgresql+asyncpg://{username}:{ctx.credential}@{host}:{port}/{database}",
        pool_pre_ping=True,
        connect_args={"server_settings": {"statement_timeout": str(STATEMENT_TIMEOUT_MS)}},
    )


class NoArgs(BaseModel):
    pass


@register
class ListTables(Tool):
    name = "list_tables"
    pack = "database"
    description = "List the tables available in the connected database."
    args_model = NoArgs
    side_effect = SideEffect.READ
    requires_connection = "database"
    timeout_s = 20.0

    async def run(self, ctx: ToolContext, args: NoArgs) -> ToolResult:  # type: ignore[override]
        if not ctx.credential or not ctx.config:
            return ToolResult.failure("not_connected", "No database is connected.")

        engine = _engine(ctx)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT table_schema, table_name FROM information_schema.tables "
                        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                        "ORDER BY table_schema, table_name"
                    )
                )
                tables = [f"{row[0]}.{row[1]}" for row in result.fetchall()]
        except SQLAlchemyError as exc:
            return ToolResult.failure("database_error", f"Could not list tables: {exc}")
        finally:
            await engine.dispose()

        return ToolResult.success({"tables": tables})


class DescribeArgs(BaseModel):
    table: str = Field(description="Table name, optionally schema-qualified")


@register
class DescribeTable(Tool):
    name = "describe_table"
    pack = "database"
    description = "Show the columns and types of one table."
    args_model = DescribeArgs
    side_effect = SideEffect.READ
    requires_connection = "database"
    timeout_s = 20.0

    async def run(self, ctx: ToolContext, args: DescribeArgs) -> ToolResult:  # type: ignore[override]
        if not ctx.credential or not ctx.config:
            return ToolResult.failure("not_connected", "No database is connected.")

        schema, _, table = args.table.rpartition(".")
        engine = _engine(ctx)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_name = :table "
                        "AND (:schema = '' OR table_schema = :schema) "
                        "ORDER BY ordinal_position"
                    ),
                    {"table": table, "schema": schema},
                )
                columns = [
                    {"name": r[0], "type": r[1], "nullable": r[2] == "YES"}
                    for r in result.fetchall()
                ]
        except SQLAlchemyError as exc:
            return ToolResult.failure("database_error", f"Could not describe that table: {exc}")
        finally:
            await engine.dispose()

        if not columns:
            return ToolResult.failure("not_found", f"No table called '{args.table}'.")
        return ToolResult.success({"table": args.table, "columns": columns})


class QueryArgs(BaseModel):
    sql: str = Field(description="A single SELECT statement")


@register
class RunQuery(Tool):
    name = "run_query"
    pack = "database"
    description = (
        f"Run one SELECT query and return the rows. Read-only; "
        f"at most {MAX_ROWS} rows are returned."
    )
    args_model = QueryArgs
    side_effect = SideEffect.READ
    requires_connection = "database"
    timeout_s = 25.0

    async def run(self, ctx: ToolContext, args: QueryArgs) -> ToolResult:  # type: ignore[override]
        if not ctx.credential or not ctx.config:
            return ToolResult.failure("not_connected", "No database is connected.")

        ok, reason = _looks_read_only(args.sql)
        if not ok:
            # A clear message so the model rewrites the query rather
            # than retrying the same thing. The database user is what
            # actually prevents a write from succeeding.
            return ToolResult.failure("not_allowed", reason)

        engine = _engine(ctx)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(args.sql.strip().rstrip(";")))
                rows = result.fetchmany(MAX_ROWS)
                columns = list(result.keys())
        except SQLAlchemyError as exc:
            return ToolResult.failure("database_error", f"The query failed: {exc}")
        finally:
            await engine.dispose()

        data: list[dict[str, Any]] = [dict(zip(columns, row, strict=False)) for row in rows]
        return ToolResult.success(
            {
                "columns": columns,
                "rows": data,
                "row_count": len(data),
                "truncated": len(data) == MAX_ROWS,
            }
        )
