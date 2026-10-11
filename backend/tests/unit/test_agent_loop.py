"""The agent loop, driven by a scripted provider.

A real model gives a different answer every time, which makes
assertions impossible and costs money and rate limit on every run. A
scripted provider returns a fixed sequence instead, so these tests are
deterministic, free and offline — the same reason phase 4 records
cassettes for the end-to-end evals.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.agent.loop import AgentLoop, Budget, StopCause
from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    ProviderUnavailableError,
    Role,
    StopReason,
    ToolCall,
    ToolSchema,
    Usage,
)
from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult


class ScriptedProvider(LLMProvider):
    """Returns prepared replies in order, then repeats the last one."""

    provider_key = "scripted"

    def __init__(self, replies: list[LLMReply]) -> None:
        super().__init__(api_key="not-used")
        self.replies = replies
        self.calls = 0

    async def complete(self, **kwargs: object) -> LLMReply:  # type: ignore[override]
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply

    async def check(self, model: str) -> None:
        return None


def _answer(text: str) -> LLMReply:
    return LLMReply(
        message=Message(role=Role.ASSISTANT, content=text),
        stop_reason=StopReason.END_TURN,
        usage=Usage(prompt_tokens=10, output_tokens=5),
        model="scripted",
    )


def _calls_tool(name: str, **arguments: object) -> LLMReply:
    return LLMReply(
        message=Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(id="c1", name=name, arguments=dict(arguments))],
        ),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(prompt_tokens=10, output_tokens=5),
        model="scripted",
    )


class EchoArgs(BaseModel):
    text: str


class EchoTool(Tool):
    name = "echo"
    pack = "test"
    description = "Return the text given to it."
    args_model = EchoArgs
    side_effect = SideEffect.READ

    async def run(self, ctx: ToolContext, args: EchoArgs) -> ToolResult:  # type: ignore[override]
        return ToolResult.success(f"echoed: {args.text}")


class ExplodingTool(Tool):
    name = "explode"
    pack = "test"
    description = "Always raises."
    args_model = EchoArgs
    side_effect = SideEffect.READ

    async def run(self, ctx: ToolContext, args: EchoArgs) -> ToolResult:  # type: ignore[override]
        raise RuntimeError("boom")


def _loop(provider: LLMProvider, tools: list[type[Tool]], **kw: object) -> AgentLoop:
    return AgentLoop(
        provider=provider,
        model="scripted",
        tools=tools,
        tool_context=ToolContext(org_id=uuid.uuid4()),
        **kw,  # type: ignore[arg-type]
    )


async def test_a_direct_answer_finishes_in_one_step() -> None:
    loop = _loop(ScriptedProvider([_answer("The bug is on line 24.")]), [])
    outcome = await loop.run(system_prompt="You are a helper.", task="What is the bug?")

    assert outcome.completed
    assert outcome.output == "The bug is on line 24."
    assert outcome.steps == 1


async def test_the_model_can_call_a_tool_and_use_the_result() -> None:
    provider = ScriptedProvider([_calls_tool("echo", text="hello"), _answer("It said hello.")])
    outcome = await _loop(provider, [EchoTool]).run(system_prompt="sys", task="echo hello")

    assert outcome.completed
    assert outcome.output == "It said hello."
    assert outcome.steps == 2

    first_result = next(e for e in outcome.events if e.type == "tool_result")
    assert first_result.payload["ok"] is True


async def test_max_steps_stops_a_looping_agent() -> None:
    """A model that keeps calling a tool forever must be stopped, or one
    confused run burns a night of free-tier quota."""
    provider = ScriptedProvider([_calls_tool("echo", text="again")])  # repeats for ever
    outcome = await _loop(provider, [EchoTool], budget=Budget(max_steps=3)).run(
        system_prompt="sys", task="loop"
    )

    assert outcome.stop_cause == StopCause.MAX_STEPS
    assert outcome.steps == 3


async def test_an_unknown_tool_is_reported_to_the_model_not_crashed() -> None:
    provider = ScriptedProvider([_calls_tool("does_not_exist"), _answer("I used a real one.")])
    outcome = await _loop(provider, [EchoTool]).run(system_prompt="sys", task="go")

    assert outcome.completed
    failed = next(e for e in outcome.events if e.type == "tool_result")
    assert failed.payload["error_class"] == "unknown_tool"


async def test_a_crashing_tool_does_not_kill_the_run() -> None:
    provider = ScriptedProvider([_calls_tool("explode", text="x"), _answer("Recovered.")])
    outcome = await _loop(provider, [ExplodingTool]).run(system_prompt="sys", task="go")

    assert outcome.completed
    assert outcome.output == "Recovered."
    failed = next(e for e in outcome.events if e.type == "tool_result")
    assert failed.payload["error_class"] == "tool_error"


async def test_bad_arguments_come_back_as_a_readable_message() -> None:
    """The model can then correct itself on the next step."""
    provider = ScriptedProvider([_calls_tool("echo", wrong_field="x"), _answer("Fixed it.")])
    outcome = await _loop(provider, [EchoTool]).run(system_prompt="sys", task="go")

    assert outcome.completed
    failed = next(e for e in outcome.events if e.type == "tool_result")
    assert failed.payload["error_class"] == "invalid_arguments"


async def test_cancellation_stops_within_one_step() -> None:
    async def always_cancelled() -> bool:
        return True

    provider = ScriptedProvider([_answer("never reached")])
    outcome = await _loop(provider, [], is_cancelled=always_cancelled).run(
        system_prompt="sys", task="go"
    )

    assert outcome.stop_cause == StopCause.CANCELLED


async def test_a_provider_outage_ends_the_run_cleanly() -> None:
    class Failing(LLMProvider):
        provider_key = "failing"

        async def complete(self, **kwargs: object) -> LLMReply:  # type: ignore[override]
            raise ProviderUnavailableError("the provider is down")

        async def check(self, model: str) -> None:
            return None

    outcome = await _loop(Failing("k"), []).run(system_prompt="sys", task="go")

    assert outcome.stop_cause == StopCause.PROVIDER_ERROR


async def test_token_usage_is_accumulated() -> None:
    provider = ScriptedProvider([_calls_tool("echo", text="a"), _answer("done")])
    outcome = await _loop(provider, [EchoTool]).run(system_prompt="sys", task="go")

    assert outcome.prompt_tokens == 20  # two calls at 10
    assert outcome.output_tokens == 10


async def test_only_the_employees_own_tools_are_offered_to_the_model() -> None:
    """A tool the employee is not allowed does not appear in the schema
    list, so as far as the model is concerned it does not exist. This
    is the main defence against prompt injection."""
    loop = _loop(ScriptedProvider([_answer("ok")]), [EchoTool])
    names = {s.name for s in loop._schemas()}

    assert names == {"echo"}
    assert "explode" not in names


_ = ToolSchema  # re-exported for readers of this module
