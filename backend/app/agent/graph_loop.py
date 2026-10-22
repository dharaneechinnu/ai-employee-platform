"""The agent loop as a LangGraph graph with a saved state.

    think -> act -> think -> ... -> answer

Same rules as `AgentLoop` (it is a subclass and reuses its model call,
tool runner, events and budgets), with one difference that is the point:
when a tool needs a person's approval, `act` calls LangGraph's
`interrupt()`. The graph's state is already saved, so the worker ends the
run and takes other jobs; when the person approves, any worker resumes
the same thread and the approved call runs. Nothing is replayed: `act`
decides what is allowed first, pauses next, and only then runs anything,
so running it again after a pause repeats no side effect.

Rejection never resumes the thread: the run is failed (see
`ApprovalService`), and its saved state is dropped.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agent.loop import (
    MAX_PARALLEL_TOOLS,
    AgentLoop,
    RunOutcome,
    StopCause,
    deserialise,
    serialise,
)
from app.agent.providers.base import LLMError, Message, Role, StopReason, ToolCall


class LoopState(TypedDict, total=False):
    # Plain dicts (see `serialise`), so the state saves as JSON-like data.
    messages: list[dict[str, Any]]
    steps: int
    prompt_tokens: int
    output_tokens: int
    stop_cause: str | None
    output: str | None


class GraphLoop(AgentLoop):
    def __init__(
        self,
        *,
        saver: BaseCheckpointSaver[Any],
        thread_id: str,
        resume: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._thread_id = thread_id
        self._resume = resume
        self._saver = saver
        self._graph = self._build()

    @property
    def resuming(self) -> bool:
        return self._resume

    # ------------------------------------------------------------- nodes

    async def _think(self, state: LoopState) -> LoopState:
        budget = self.budget
        budget.steps_used = state.get("steps", 0)
        budget.tokens_used = state.get("prompt_tokens", 0) + state.get("output_tokens", 0)

        if cause := budget.exceeded():
            await self._emit("run_stopped", cause=cause)
            return {"stop_cause": cause}
        if await self.cancel_requested():
            await self._emit("run_stopped", cause=StopCause.CANCELLED)
            return {"stop_cause": StopCause.CANCELLED}

        await self._emit("thinking", step=budget.steps_used + 1)
        messages = deserialise({"messages": state["messages"]})
        try:
            reply = await self._complete(messages)
        except LLMError as exc:
            await self._emit("provider_error", error=type(exc).__name__, retryable=exc.retryable)
            return {"stop_cause": StopCause.PROVIDER_ERROR, "output": str(exc)}

        await self._emit(
            "llm_call",
            model=reply.model,
            prompt_tokens=reply.usage.prompt_tokens,
            output_tokens=reply.usage.output_tokens,
            latency_ms=reply.latency_ms,
        )
        messages.append(reply.message)
        update: LoopState = {
            "messages": serialise(messages)["messages"],
            "steps": state.get("steps", 0) + 1,
            "prompt_tokens": state.get("prompt_tokens", 0) + reply.usage.prompt_tokens,
            "output_tokens": state.get("output_tokens", 0) + reply.usage.output_tokens,
        }
        if reply.stop_reason is not StopReason.TOOL_USE or not reply.tool_calls:
            await self._emit("run_finished", cause=StopCause.COMPLETED)
            update["stop_cause"] = StopCause.COMPLETED
            update["output"] = reply.text
        return update

    async def _act(self, state: LoopState) -> LoopState:
        messages = deserialise({"messages": state["messages"]})
        calls = messages[-1].tool_calls

        # 1. Decide, with no side effects: this node runs again after a pause.
        verdicts = {
            c.id: self._check_policy(c.name) if self._check_policy else ("auto", "") for c in calls
        }

        # 2. Pause for every call that needs a person, one at a time. On the
        #    run after a pause each earlier answer is replayed from the saved
        #    state and the next unanswered call pauses again.
        approved: set[str] = set()
        for call in calls:
            setting, reason = verdicts[call.id]
            if setting == "ask":
                interrupt(
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                        "reason": reason,
                    }
                )
                approved.add(call.id)

        # 3. Now act: blocked calls get an explanation, the rest run.
        results: dict[str, str] = {}
        runnable: list[ToolCall] = []
        for call in calls:
            setting, reason = verdicts[call.id]
            if setting == "blocked":
                await self._emit("tool_blocked", tool=call.name, reason=reason)
                results[call.id] = (
                    f"'{call.name}' is not permitted ({reason}). Do not try it again; use a "
                    "different approach or explain that you cannot complete this."
                )
            else:
                if call.id in approved:
                    await self._emit("approval_granted", tool=call.name)
                runnable.append(call)

        for start in range(0, len(runnable), MAX_PARALLEL_TOOLS):
            batch = runnable[start : start + MAX_PARALLEL_TOOLS]
            if len(batch) == 1:
                done = [await self._run_tool(batch[0])]
            else:
                await self._emit("parallel_started", count=len(batch))
                done = list(await asyncio.gather(*(self._run_tool(c) for c in batch)))
            for call, result in zip(batch, done, strict=True):
                results[call.id] = result.as_text()

        # A reply to every call, in the order they were asked.
        for call in calls:
            messages.append(
                Message(
                    role=Role.TOOL,
                    content=results[call.id],
                    tool_call_id=call.id,
                    name=call.name,
                )
            )
        return {"messages": serialise(messages)["messages"]}

    # ------------------------------------------------------------- graph

    def _build(self) -> Any:
        def after_think(state: LoopState) -> str:
            return END if state.get("stop_cause") else "act"

        graph = StateGraph(LoopState)
        graph.add_node("think", self._think)
        graph.add_node("act", self._act)
        graph.add_edge(START, "think")
        graph.add_conditional_edges("think", after_think, ["act", END])
        graph.add_edge("act", "think")
        return graph.compile(checkpointer=self._saver)

    # --------------------------------------------------------------- run

    async def run(
        self, *, system_prompt: str, task: str, history: list[Message] | None = None
    ) -> RunOutcome:
        config = {"configurable": {"thread_id": self._thread_id}}
        await self._emit("run_started", model=self.model, tools=list(self.tools))

        if self._resume:
            snapshot = await self._graph.aget_state(config)
            waiting = [i for t in snapshot.tasks for i in t.interrupts]
            if not waiting:
                # Nothing is paused under this run: its saved state is gone.
                await self._emit("run_stopped", cause="state_lost")
                return self._outcome("state_lost", None, 0, 0)
            await self._emit("approval_granted", tool=waiting[0].value["name"])
            graph_input: Any = Command(resume=True)
        else:
            graph_input = {
                "messages": serialise(
                    [
                        Message(role=Role.SYSTEM, content=system_prompt),
                        *(history or []),
                        Message(role=Role.USER, content=task),
                    ]
                )["messages"],
                "steps": 0,
                "prompt_tokens": 0,
                "output_tokens": 0,
            }

        final = await self._graph.ainvoke(graph_input, config)
        state = await self._graph.aget_state(config)
        values: LoopState = state.values
        prompt_tokens = values.get("prompt_tokens", 0)
        output_tokens = values.get("output_tokens", 0)
        self.budget.steps_used = values.get("steps", 0)

        if final.get("__interrupt__"):
            asked = final["__interrupt__"][0].value
            await self._emit("approval_requested", tool=asked["name"], reason=asked["reason"])
            outcome = self._outcome(StopCause.AWAITING_APPROVAL, None, prompt_tokens, output_tokens)
            outcome.pending_tool_call = {
                "id": asked["id"],
                "name": asked["name"],
                "arguments": asked["arguments"],
            }
            return outcome

        # Finished for good: nothing will resume this thread.
        await self._saver.adelete_thread(self._thread_id)
        return self._outcome(
            values.get("stop_cause") or StopCause.PROVIDER_ERROR,
            values.get("output"),
            prompt_tokens,
            output_tokens,
        )
