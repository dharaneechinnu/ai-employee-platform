"""The run as a LangGraph graph.

The point of this step is that nothing changes for the person, so the
main test runs the same scripted conversation through the loop directly
and through the graph and expects the same outcome.
"""

import uuid

from app.agent.graph import build_graph, run_in_graph
from app.agent.loop import AgentLoop, Budget
from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from app.agent.tools.base import ToolContext
from app.agent.tools.packs.calculator import Calculator

CTX = ToolContext(owner_id=uuid.uuid4())


class Scripted(LLMProvider):
    provider_key = "scripted"

    def __init__(self, replies: list[LLMReply]) -> None:
        super().__init__(api_key="x")
        self.replies = replies
        self.calls: list[dict] = []

    async def complete(self, **kwargs: object) -> LLMReply:  # type: ignore[override]
        self.calls.append(kwargs)
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]

    async def check(self, model: str) -> None:
        return None


def answer(text: str) -> LLMReply:
    return LLMReply(
        message=Message(role=Role.ASSISTANT, content=text),
        stop_reason=StopReason.END_TURN,
        usage=Usage(10, 5),
        model="m",
    )


def asks(name: str, arguments: dict) -> LLMReply:
    return LLMReply(
        message=Message(
            role=Role.ASSISTANT, tool_calls=[ToolCall(id="c1", name=name, arguments=arguments)]
        ),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(10, 5),
        model="m",
    )


def make_loop(provider: Scripted) -> AgentLoop:
    return AgentLoop(
        provider=provider,
        model="m",
        tools=[Calculator],
        tool_context=CTX,
        budget=Budget(max_steps=5),
    )


async def test_the_graph_gives_the_same_outcome_as_the_loop() -> None:
    script = [asks("calculator", {"expression": "6 * 7"}), answer("It is 42.")]

    direct = await make_loop(Scripted(script)).run(system_prompt="s", task="6 times 7?")
    graphed = await run_in_graph(make_loop(Scripted(script)), system_prompt="s", task="6 times 7?")

    assert graphed.stop_cause == direct.stop_cause == "completed"
    assert graphed.output == direct.output == "It is 42."
    assert graphed.steps == direct.steps == 2
    assert (graphed.prompt_tokens, graphed.output_tokens) == (
        direct.prompt_tokens,
        direct.output_tokens,
    )
    assert [e.type for e in graphed.events] == [e.type for e in direct.events]


async def test_the_graph_has_one_node_for_now() -> None:
    graph = build_graph(make_loop(Scripted([answer("hi")])))
    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"agent"}


async def test_a_paused_run_still_pauses_inside_the_graph() -> None:
    """An approval pause must survive the wrapper: same stop cause, and
    the saved state a worker needs to resume later."""
    loop = AgentLoop(
        provider=Scripted([asks("calculator", {"expression": "1+1"})]),
        model="m",
        tools=[Calculator],
        tool_context=CTX,
        check_policy=lambda name: ("ask", "needs a person"),
    )
    outcome = await run_in_graph(loop, system_prompt="s", task="t")
    assert outcome.paused
    assert outcome.pending_tool_call == {
        "id": "c1",
        "name": "calculator",
        "arguments": {"expression": "1+1"},
    }
    assert outcome.saved_state is not None
