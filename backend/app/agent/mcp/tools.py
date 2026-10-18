"""Turn an MCP server's tools into platform tools.

Built-in tools are Python classes registered at import. MCP tools
depend on what each company connected, so they are built per company
from the cached tool list, and never enter the global registry: one
company's tools cannot appear in another's run.

Each one is an ordinary `Tool` subclass, so everything downstream
(permissions, approvals, the run timeline, delegation) needs no special
case. The name says where it came from: `mcp__crm__find_customer` is
the `find_customer` tool on the server this company called "crm".
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from app.agent.mcp.client import McpClient, McpError
from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult

PREFIX = "mcp__"
# Every provider accepts names matching this, and none longer than 64.
_UNSAFE = re.compile(r"[^a-zA-Z0-9_-]")
MAX_NAME = 64
MAX_DESCRIPTION = 1000


def connection_kind(slug: str) -> str:
    return f"mcp:{slug}"


def tool_name(slug: str, remote_name: str) -> str:
    return f"{PREFIX}{slug}__{_UNSAFE.sub('_', remote_name)}"[:MAX_NAME]


def effect_of(annotations: dict[str, Any] | None) -> SideEffect:
    """What the server says the tool does to the world.

    A server that marks a tool read-only gets "read"; one that marks it
    destructive gets "destructive". Anything unlabelled is treated as
    "write", so by default it waits for a person to approve it: a
    server's silence is not a promise that a tool is harmless.
    """
    annotations = annotations or {}
    if annotations.get("readOnlyHint") is True:
        return SideEffect.READ
    if annotations.get("destructiveHint") is True:
        return SideEffect.DESTRUCTIVE
    return SideEffect.WRITE


def describe(raw: dict[str, Any]) -> dict[str, Any] | None:
    """The cached form of one tool from `tools/list`, or None if unusable."""
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None
    schema = raw.get("inputSchema")
    annotations = raw.get("annotations") or {}
    return {
        "name": name,
        "title": raw.get("title") or annotations.get("title") or None,
        "description": (raw.get("description") or "").strip()[:MAX_DESCRIPTION],
        "input_schema": _clean_schema(schema if isinstance(schema, dict) else {}),
        "effect": effect_of(annotations).value,
    }


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """A schema every provider accepts: an object, without `$schema`,
    which Gemini rejects."""
    cleaned = {k: v for k, v in schema.items() if k != "$schema"}
    cleaned["type"] = "object"
    cleaned.setdefault("properties", {})
    return cleaned


class _AnyArgs(BaseModel):
    """The server validates its own arguments, against its own schema,
    and a bad call comes back as an error the model can read."""

    model_config = ConfigDict(extra="allow")


class McpTool(Tool):
    """Base for the generated classes. Never registered itself."""

    args_model = _AnyArgs
    supports_dry_run = True
    timeout_s = 30.0

    remote_name: ClassVar[str]
    server_name: ClassVar[str]
    title: ClassVar[str | None]
    input_schema: ClassVar[dict[str, Any]]

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        return cls.input_schema

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolResult:
        arguments = args.model_dump()
        if ctx.dry_run and self.side_effect is not SideEffect.READ:
            return ToolResult.success(
                {"dry_run": True, "would_call": self.remote_name, "with": arguments}
            )

        url = (ctx.config or {}).get("url")
        if not url:
            return ToolResult.failure("not_connected", f"{self.server_name} is not connected.")

        try:
            async with McpClient(url, token=ctx.credential or None) as client:
                result = await client.call_tool(self.remote_name, arguments)
        except McpError as exc:
            return ToolResult.failure(exc.error_class, exc.message)

        text = _result_text(result)
        if result.get("isError"):
            # The tool ran and said no. Passed on as-is, so the model can
            # read why and try again differently.
            return ToolResult.failure("tool_error", text or "The tool reported an error.")
        return ToolResult.success(text or "Done. The tool returned nothing.")


def _result_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind == "resource":
            resource = item.get("resource") or {}
            parts.append(str(resource.get("text") or f"[file: {resource.get('uri', '')}]"))
        elif kind == "resource_link":
            parts.append(f"[link: {item.get('name') or item.get('uri', '')}]")
        elif kind in ("image", "audio"):
            parts.append(f"[{kind} returned, not shown]")
    if not parts and result.get("structuredContent") is not None:
        import json

        parts.append(json.dumps(result["structuredContent"], default=str))
    return "\n".join(parts)


def build_tools(slug: str, server_name: str, specs: list[dict[str, Any]]) -> list[type[Tool]]:
    """One Tool class per cached tool of one server."""
    built: list[type[Tool]] = []
    seen: set[str] = set()
    for spec in specs:
        name = tool_name(slug, spec["name"])
        if name in seen:  # two remote names that clean up the same way
            continue
        seen.add(name)
        description = spec.get("description") or spec.get("title") or spec["name"]
        built.append(
            type(
                f"Mcp_{name}",
                (McpTool,),
                {
                    "name": name,
                    "pack": f"{PREFIX}{slug}",
                    "description": f"{description} (from {server_name})"[:MAX_DESCRIPTION],
                    "side_effect": SideEffect(spec.get("effect", SideEffect.WRITE.value)),
                    "requires_connection": connection_kind(slug),
                    "remote_name": spec["name"],
                    "server_name": server_name,
                    "title": spec.get("title"),
                    "input_schema": spec.get("input_schema")
                    or {"type": "object", "properties": {}},
                },
            )
        )
    return built
