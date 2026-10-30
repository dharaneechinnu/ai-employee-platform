"""The run, as a LangGraph graph.

Step 4a of the multi-agent plan: the graph has ONE node, and that node
runs the existing `AgentLoop` unchanged. So budgets, cancellation,
parallel tools, permission checks and approval pauses behave exactly as
before. What changes is the shape around them: the run is now a graph,
which is what the supervisor and the review loop (step 4b) get added to
as more nodes and edges.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.loop import AgentLoop, RunOutcome
from app.agent.providers.base import Message


class RunState(TypedDict, total=False):
    system_prompt: str
    task: str
    history: list[Message] | None
    outcome: RunOutcome


def build_graph(loop: AgentLoop) -> Any:
    """A compiled graph whose only node is `loop`."""

    async def agent(state: RunState) -> RunState:
        outcome = await loop.run(
            system_prompt=state["system_prompt"],
            task=state["task"],
            history=state.get("history"),
        )
        return {"outcome": outcome}

    graph = StateGraph(RunState)
    graph.add_node("agent", agent)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)
    return graph.compile()


async def run_in_graph(
    loop: AgentLoop, *, system_prompt: str, task: str, history: list[Message] | None = None
) -> RunOutcome:
    final = await build_graph(loop).ainvoke(
        {"system_prompt": system_prompt, "task": task, "history": history}
    )
    outcome: RunOutcome = final["outcome"]
    return outcome
