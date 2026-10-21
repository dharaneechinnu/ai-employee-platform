"""The builder's one tool: show the person a draft agent.

It changes nothing. The draft is shown as a card and nothing exists
until the person presses Create, so there is no approval to wait for and
no way for a model (or a poisoned web page it read) to make an agent on
its own. It is only offered in the builder chat, never to anything else.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult


class ProposeAgentArgs(BaseModel):
    name: str = Field(min_length=1, max_length=80, description="A short name, e.g. Friday Digest")
    description: str = Field(max_length=300, description="One sentence: what it is for")
    instructions: str = Field(
        min_length=20,
        max_length=8000,
        description="How the agent should behave, written to the agent as 'You are ...'",
    )
    tools: list[str] | None = Field(
        default=None,
        description="Names of the tools it may use, from the list you were given; "
        "null to allow everything the person allows",
    )


class ProposeAgent(Tool):
    """Not in the global registry: only the builder chat is given it."""

    name = "propose_agent"
    pack = "builder"
    description = (
        "Show the person a draft of the agent you have designed with them. Call it "
        "again with changes whenever they ask for any. The person decides whether to "
        "create it."
    )
    args_model = ProposeAgentArgs
    side_effect = SideEffect.READ
    timeout_s = 5.0

    async def run(self, ctx: ToolContext, args: ProposeAgentArgs) -> ToolResult:  # type: ignore[override]
        return ToolResult.success(
            {"shown": True, "note": "The draft is on the person's screen. Say what it does."}
        )
