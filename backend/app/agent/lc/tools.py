"""Our tools as LangChain tools.

A LangChain tool is a name, a description, an argument schema and a
function. Ours already have all four, so wrapping is thin on purpose:
the call goes through `Tool.execute`, which validates the arguments,
resolves the app connection and returns a failure as text. Permissions
are not re-implemented here; the loop (or a graph node) checks them
before it calls the tool.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from app.agent.tools.base import Tool, ToolContext


def to_langchain_tool(tool: type[Tool], ctx: ToolContext) -> StructuredTool:
    async def call(**arguments: object) -> str:
        result = await tool().execute(ctx, dict(arguments))
        return result.as_text()

    return StructuredTool.from_function(
        coroutine=call,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_model,
    )


def to_langchain_tools(tools: list[type[Tool]], ctx: ToolContext) -> list[StructuredTool]:
    return [to_langchain_tool(t, ctx) for t in tools]
