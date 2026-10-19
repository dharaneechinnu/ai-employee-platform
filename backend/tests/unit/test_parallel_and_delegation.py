"""Parallel tool execution and the delegation limits."""

from __future__ import annotations

import asyncio
import time
import uuid

from pydantic import BaseModel

from app.agent.loop import MAX_PARALLEL_TOOLS, AgentLoop
from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.packs.delegation import MAX_DELEGATION_DEPTH, DelegateToSpecialist


class SleepArgs(BaseModel):
    ms: int = 100


class SleepyTool(Tool):
    """Stands in for a tool that waits on the network."""

    name = "sleepy"
    pack = "test"
    description = "Waits, then returns."
    args_model = SleepArgs
    side_effect = SideEffect.READ

    async def run(self, ctx: ToolContext, args: SleepArgs) -> ToolResult:  # type: ignore[override]
        await asyncio.sleep(args.ms / 1000)
        return ToolResult.success(f"slept {args.ms}ms")


class ScriptedProvider(LLMProvider):
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


def _calls(*names_and_args: tuple[str, dict[str, object]]) -> LLMReply:
    return LLMReply(
        message=Message(
            role=Role.ASSISTANT,
            tool_calls=[
                ToolCall(id=f"c{i}", name=name, arguments=args)
                for i, (name, args) in enumerate(names_and_args)
            ],
        ),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(prompt_tokens=10, output_tokens=5),
        model="scripted",
    )


async def test_independent_tool_calls_run_together() -> None:
    """Most of a tool call is network wait, so three 150ms calls should
    take about 150ms, not 450ms."""
    provider = ScriptedProvider(
        [
            _calls(("sleepy", {"ms": 150}), ("sleepy", {"ms": 150}), ("sleepy", {"ms": 150})),
            _answer("done"),
        ]
    )
    loop = AgentLoop(
        provider=provider,
        model="scripted",
        tools=[SleepyTool],
        tool_context=ToolContext(owner_id=uuid.uuid4()),
    )

    started = time.perf_counter()
    outcome = await loop.run(system_prompt="sys", task="go")
    elapsed = time.perf_counter() - started

    assert outcome.completed
    # Generous bound: the point is that it is nowhere near 450ms.
    assert elapsed < 0.4, f"took {elapsed:.2f}s, so the calls ran one at a time"
    assert any(e.type == "parallel_started" for e in outcome.events)


async def test_a_single_tool_call_is_not_reported_as_parallel() -> None:
    provider = ScriptedProvider([_calls(("sleepy", {"ms": 10})), _answer("done")])
    loop = AgentLoop(
        provider=provider,
        model="scripted",
        tools=[SleepyTool],
        tool_context=ToolContext(owner_id=uuid.uuid4()),
    )

    outcome = await loop.run(system_prompt="sys", task="go")
    assert not any(e.type == "parallel_started" for e in outcome.events)


async def test_parallelism_is_capped() -> None:
    """Each call is also a slice of the rate-limit budget, so an
    unbounded fan-out would starve every other task in the queue."""
    calls = tuple(("sleepy", {"ms": 20}) for _ in range(7))
    provider = ScriptedProvider([_calls(*calls), _answer("done")])
    loop = AgentLoop(
        provider=provider,
        model="scripted",
        tools=[SleepyTool],
        tool_context=ToolContext(owner_id=uuid.uuid4()),
    )

    outcome = await loop.run(system_prompt="sys", task="go")
    batches = [e for e in outcome.events if e.type == "parallel_started"]

    assert all(e.payload["count"] <= MAX_PARALLEL_TOOLS for e in batches)
    # Seven calls at three per batch: 3, 3, then a single one that is
    # run directly rather than announced as parallel.
    assert len(batches) == 2


async def test_all_parallel_results_reach_the_model() -> None:
    provider = ScriptedProvider(
        [_calls(("sleepy", {"ms": 5}), ("sleepy", {"ms": 5})), _answer("done")]
    )
    loop = AgentLoop(
        provider=provider,
        model="scripted",
        tools=[SleepyTool],
        tool_context=ToolContext(owner_id=uuid.uuid4()),
    )

    outcome = await loop.run(system_prompt="sys", task="go")
    results = [e for e in outcome.events if e.type == "tool_result"]

    assert len(results) == 2
    assert all(e.payload["ok"] for e in results)


# ----------------------------------------------------------------- delegation


async def test_a_specialist_cannot_delegate_onward() -> None:
    """Depth is capped at 1. Chaining agents multiplies error rates:
    at 80% each, three levels is a coin flip, and a mistake by the
    first becomes the second's input."""
    tool = DelegateToSpecialist()
    ctx = ToolContext(
        owner_id=uuid.uuid4(),
        config={"_session": object(), "_depth": MAX_DELEGATION_DEPTH},
    )

    result = await tool.execute(ctx, {"specialist_name": "Anyone", "task": "do this"})

    assert not result.ok
    assert result.error_class == "depth_limit"


async def test_delegation_needs_a_session() -> None:
    tool = DelegateToSpecialist()
    result = await tool.execute(
        ToolContext(owner_id=uuid.uuid4()), {"specialist_name": "A", "task": "t"}
    )

    assert not result.ok
    assert result.error_class == "unavailable"


async def test_too_many_specialists_is_refused() -> None:
    tool = DelegateToSpecialist()
    ctx = ToolContext(
        owner_id=uuid.uuid4(),
        config={
            "_session": object(),
            "_depth": 0,
            "_delegated_to": {"One", "Two", "Three"},
        },
    )

    result = await tool.execute(ctx, {"specialist_name": "Four", "task": "t"})

    assert not result.ok
    assert result.error_class == "too_many_specialists"


def test_delegation_is_labelled_as_a_write() -> None:
    """A specialist may take write actions of its own, so delegation is
    not a read."""
    assert DelegateToSpecialist.side_effect is SideEffect.WRITE


def test_specialists_follow_the_company_permission_rules() -> None:
    """Delegating must not be a way round Permissions. "Ask me first"
    becomes a refusal, because a specialist cannot pause for a person;
    its manager does that step instead, with the normal approval."""
    from app.agent.tools.packs.delegation import specialist_policy
    from app.db.models.policy import PolicySetting
    from app.services.policy_service import Decision

    rules = {
        "get_webpage": PolicySetting.AUTO,
        "gmail_send": PolicySetting.ASK,
        "send_email": PolicySetting.BLOCKED,
    }

    class Resolver:
        def evaluate(self, tool_name: str) -> Decision:
            return Decision(rules[tool_name], "set by your company for this tool")

    check = specialist_policy(Resolver())
    assert check("get_webpage")[0] == "auto"
    assert check("send_email")[0] == "blocked"
    setting, reason = check("gmail_send")
    assert setting == "blocked"
    assert "manager" in reason
