"""The agent loop.

    think -> ask for a tool -> run it -> think again -> ... -> answer

Written by hand rather than taken from a framework, so the behaviour
that matters is explicit and visible: budgets, cancellation, how tool
failures reach the model, and where the permission check will slot in.
Phase 7 swaps the mechanism for LangGraph; these rules stay.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.providers.base import (
    LLMError,
    LLMProvider,
    LLMReply,
    Message,
    ProviderRequestError,
    Role,
    StopReason,
    ToolCall,
    ToolSchema,
)
from app.agent.tools.base import Tool, ToolContext, ToolResult
from app.core.observability import get_logger

log = get_logger(__name__)

# Most of a tool call is waiting on the network, so independent
# calls run together. Capped: each one also costs rate-limit budget,
# and an unbounded fan-out starves every other task in the queue.
MAX_PARALLEL_TOOLS = 3

# What providers say when a model cannot take tools at all. A person's own
# model may be a small or older one, and the run should still answer, only
# without tools, rather than fail on the first call.
_NO_TOOLS = re.compile(
    r"(does not|doesn'?t|not) support[^.]{0,40}(tool|function)|"
    r"(tool|function)[ _-]?(use|call\w*)?[^.]{0,40}(not supported|unsupported)|"
    r"tools? (is|are) not (supported|available)",
    re.IGNORECASE,
)


def rejects_tools(exc: LLMError) -> bool:
    return isinstance(exc, ProviderRequestError) and bool(_NO_TOOLS.search(exc.message))


class StopCause(str):
    COMPLETED = "completed"
    MAX_STEPS = "max_steps"
    MAX_TOKENS = "max_tokens"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PROVIDER_ERROR = "provider_error"
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass(slots=True)
class Budget:
    """Seatbelts.

    A confused agent will loop - try, fail, try again - and every pass
    costs money and a slice of the free-tier rate limit. Without a cap
    one bad run can burn a night's quota.
    """

    max_steps: int = 15
    max_tokens: int = 200_000
    max_seconds: float = 600.0

    steps_used: int = 0
    tokens_used: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def exceeded(self) -> str | None:
        if self.steps_used >= self.max_steps:
            return StopCause.MAX_STEPS
        if self.tokens_used >= self.max_tokens:
            return StopCause.MAX_TOKENS
        if time.monotonic() - self.started_at >= self.max_seconds:
            return StopCause.TIMEOUT
        return None


@dataclass(slots=True)
class AgentEvent:
    type: str
    payload: dict[str, Any]


@dataclass(slots=True)
class RunOutcome:
    stop_cause: str
    output: str | None
    steps: int
    prompt_tokens: int
    output_tokens: int
    events: list[AgentEvent]

    # Set only when the run paused for approval. The conversation so
    # far, plus the call that triggered the pause, so another worker
    # can pick it up after the human decides.
    saved_state: dict[str, Any] | None = None
    pending_tool_call: dict[str, Any] | None = None

    @property
    def completed(self) -> bool:
        return self.stop_cause == StopCause.COMPLETED

    @property
    def paused(self) -> bool:
        return self.stop_cause == StopCause.AWAITING_APPROVAL


EventSink = Callable[[AgentEvent], Awaitable[None]]
CancelCheck = Callable[[], Awaitable[bool]]
# Returns (setting, reason). setting is 'auto', 'ask' or 'blocked'.
PolicyCheck = Callable[[str], tuple[str, str]]


class AgentLoop:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        tools: list[type[Tool]],
        tool_context: ToolContext,
        budget: Budget | None = None,
        temperature: float = 0.2,
        on_event: EventSink | None = None,
        is_cancelled: CancelCheck | None = None,
        check_policy: PolicyCheck | None = None,
        resume_from: dict[str, Any] | None = None,
        approved_call: dict[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.tools = {t.name: t for t in tools}
        self.tool_context = tool_context
        self.budget = budget or Budget()
        self.temperature = temperature
        self._on_event = on_event
        self._is_cancelled = is_cancelled
        self._check_policy = check_policy
        self._resume_from = resume_from
        self._approved_call = approved_call
        self._events: list[AgentEvent] = []
        self._tools_unsupported = False

    @property
    def resuming(self) -> bool:
        """True when this run continues one that paused for approval."""
        return self._resume_from is not None or self._approved_call is not None

    async def cancel_requested(self) -> bool:
        return bool(self._is_cancelled and await self._is_cancelled())

    async def _emit(self, type_: str, **payload: Any) -> None:
        event = AgentEvent(type=type_, payload=payload)
        self._events.append(event)
        if self._on_event:
            await self._on_event(event)

    def _schemas(self) -> list[ToolSchema]:
        return [
            ToolSchema(name=t.name, description=t.description, parameters=t.json_schema())
            for t in self.tools.values()
        ]

    async def _complete(self, messages: list[Message]) -> LLMReply:
        """One model call. A model that cannot take tools is retried once
        without them (and told so), instead of failing the run."""
        try:
            return await self.provider.complete(
                messages=messages,
                model=self.model,
                tools=None if self._tools_unsupported else (self._schemas() or None),
                temperature=self.temperature,
            )
        except LLMError as exc:
            if self._tools_unsupported or not self.tools or not rejects_tools(exc):
                raise
        # This model cannot take tools. Carry on without them.
        self._tools_unsupported = True
        await self._emit("tools_unsupported", model=self.model)
        messages.append(
            Message(
                role=Role.USER,
                content=(
                    "Note: this AI cannot use tools, so none are available. "
                    "Answer from what you know and say what you could not check."
                ),
            )
        )
        return await self.provider.complete(
            messages=messages, model=self.model, tools=None, temperature=self.temperature
        )

    async def run(
        self, *, system_prompt: str, task: str, history: list[Message] | None = None
    ) -> RunOutcome:
        """`history` is the earlier turns of a conversation, as plain user
        and assistant messages, placed between the instructions and the
        new request."""
        messages: list[Message] = (
            deserialise(self._resume_from)
            if self._resume_from
            else [
                Message(role=Role.SYSTEM, content=system_prompt),
                *(history or []),
                Message(role=Role.USER, content=task),
            ]
        )
        prompt_tokens = output_tokens = 0

        await self._emit("run_started", model=self.model, tools=list(self.tools))

        if self._approved_call:
            # A human approved exactly this call, so it runs without
            # another policy check. Re-checking would pause again on the
            # same step and the run could never finish.
            call = ToolCall(
                id=self._approved_call["id"],
                name=self._approved_call["name"],
                arguments=self._approved_call["arguments"],
            )
            await self._emit("approval_granted", tool=call.name)
            result = await self._run_tool(call)
            messages.append(
                Message(
                    role=Role.TOOL,
                    content=result.as_text(),
                    tool_call_id=call.id,
                    name=call.name,
                )
            )

        while True:
            # Budget first: stop a runaway before it costs anything more.
            if cause := self.budget.exceeded():
                await self._emit("run_stopped", cause=cause)
                return self._outcome(cause, None, prompt_tokens, output_tokens)

            # Then cancellation, so Cancel takes effect within one step.
            if self._is_cancelled and await self._is_cancelled():
                await self._emit("run_stopped", cause=StopCause.CANCELLED)
                return self._outcome(StopCause.CANCELLED, None, prompt_tokens, output_tokens)

            await self._emit("thinking", step=self.budget.steps_used + 1)

            try:
                reply = await self._complete(messages)
            except LLMError as exc:
                await self._emit(
                    "provider_error", error=type(exc).__name__, retryable=exc.retryable
                )
                return self._outcome(
                    StopCause.PROVIDER_ERROR, str(exc), prompt_tokens, output_tokens
                )

            prompt_tokens += reply.usage.prompt_tokens
            output_tokens += reply.usage.output_tokens
            self.budget.tokens_used += reply.usage.total
            self.budget.steps_used += 1

            await self._emit(
                "llm_call",
                model=reply.model,
                prompt_tokens=reply.usage.prompt_tokens,
                output_tokens=reply.usage.output_tokens,
                latency_ms=reply.latency_ms,
            )

            messages.append(reply.message)

            if reply.stop_reason is not StopReason.TOOL_USE or not reply.tool_calls:
                await self._emit("run_finished", cause=StopCause.COMPLETED)
                return self._outcome(StopCause.COMPLETED, reply.text, prompt_tokens, output_tokens)

            # Split the batch first: a blocked call needs no work, and a
            # call needing approval ends the turn, so neither should be
            # started concurrently with the rest.
            runnable: list[ToolCall] = []

            for call in reply.tool_calls:
                setting, reason = (
                    self._check_policy(call.name) if self._check_policy else ("auto", "")
                )

                if setting == "blocked":
                    await self._emit("tool_blocked", tool=call.name, reason=reason)
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=(
                                f"'{call.name}' is not permitted ({reason}). "
                                "Do not try it again; use a different approach or explain "
                                "that you cannot complete this."
                            ),
                            tool_call_id=call.id,
                            name=call.name,
                        )
                    )
                    continue

                if setting == "ask":
                    # Return rather than wait. A human may take hours and
                    # the worker has other jobs; the saved state lets a
                    # different process resume this run later.
                    await self._emit("approval_requested", tool=call.name, reason=reason)
                    outcome = self._outcome(
                        StopCause.AWAITING_APPROVAL, None, prompt_tokens, output_tokens
                    )
                    outcome.saved_state = serialise(messages)
                    outcome.pending_tool_call = {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    return outcome

                runnable.append(call)

            for batch_start in range(0, len(runnable), MAX_PARALLEL_TOOLS):
                batch = runnable[batch_start : batch_start + MAX_PARALLEL_TOOLS]

                if len(batch) == 1:
                    results = [await self._run_tool(batch[0])]
                else:
                    await self._emit("parallel_started", count=len(batch))
                    results = list(await asyncio.gather(*(self._run_tool(c) for c in batch)))

                for call, result in zip(batch, results, strict=True):
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=result.as_text(),
                            tool_call_id=call.id,
                            name=call.name,
                        )
                    )

    async def _run_tool(self, call: ToolCall) -> ToolResult:
        await self._emit("tool_call", tool=call.name, arguments=call.arguments)

        tool_cls = self.tools.get(call.name)
        if tool_cls is None:
            # The model asked for something it does not have. Tell it so
            # it can pick a real tool, rather than failing the run.
            result = ToolResult.failure(
                "unknown_tool",
                f"There is no tool called '{call.name}'. "
                f"Available tools: {', '.join(sorted(self.tools)) or 'none'}.",
            )
            await self._emit("tool_result", tool=call.name, **result.summary())
            return result

        try:
            result = await asyncio.wait_for(
                tool_cls().execute(self.tool_context, call.arguments),
                timeout=tool_cls.timeout_s,
            )
        except TimeoutError:
            result = ToolResult.failure(
                "timeout", f"{call.name} did not finish within {tool_cls.timeout_s} seconds."
            )
        except Exception as exc:
            log.exception("tool_crashed", tool=call.name)
            result = ToolResult.failure("tool_error", f"{type(exc).__name__}: {exc}")

        await self._emit("tool_result", tool=call.name, **result.summary())
        return result

    def _outcome(
        self, cause: str, output: str | None, prompt_tokens: int, output_tokens: int
    ) -> RunOutcome:
        return RunOutcome(
            stop_cause=cause,
            output=output,
            steps=self.budget.steps_used,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            events=self._events,
        )


def serialise(messages: list[Message]) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": m.role.value,
                "content": m.content,
                "tool_call_id": m.tool_call_id,
                "name": m.name,
                "raw": m.raw,
                "raw_from": m.raw_from,
                "tool_calls": [
                    {"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls
                ],
            }
            for m in messages
        ]
    }


def deserialise(state: dict[str, Any]) -> list[Message]:
    return [
        Message(
            role=Role(m["role"]),
            content=m.get("content"),
            tool_call_id=m.get("tool_call_id"),
            name=m.get("name"),
            raw=m.get("raw"),
            raw_from=m.get("raw_from"),
            tool_calls=[
                ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"])
                for c in m.get("tool_calls", [])
            ],
        )
        for m in state.get("messages", [])
    ]


def new_run_id() -> uuid.UUID:
    return uuid.uuid4()
