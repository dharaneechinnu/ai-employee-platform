"""Step 5: retry by kind of failure, a stronger AI for a helper that could not
finish, and per-helper cost and outcome numbers."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    ProviderAuthError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderUnavailableError,
    Role,
    StopReason,
    ToolCall,
    Usage,
    parse_retry_after,
)
from app.agent.providers.fallback import (
    MAX_PAUSE_S,
    RATE_LIMIT_PAUSES,
    FallbackProvider,
    Option,
)
from app.agent.team import TEAM_TOKEN_BUDGET, Team, run_specialist
from app.agent.tools.base import ToolContext
from app.agent.tools.packs.calculator import Calculator


def reply(text: str | None = None, calls: list[ToolCall] | None = None) -> LLMReply:
    return LLMReply(
        message=Message(role=Role.ASSISTANT, content=text, tool_calls=calls or []),
        stop_reason=StopReason.TOOL_USE if calls else StopReason.END_TURN,
        usage=Usage(10, 5),
        model="m",
    )


class Scripted(LLMProvider):
    """Raises or returns each item in turn; the last one repeats."""

    provider_key = "scripted"

    def __init__(self, *items: Any) -> None:
        super().__init__(api_key="x")
        self.items = list(items)
        self.calls = 0

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        item = self.items[min(self.calls, len(self.items) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item

    async def check(self, model: str) -> None:
        return None


class Clock:
    """Stands in for asyncio.sleep: records the waits, takes no time."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def option(provider: LLMProvider, key: str = "a") -> Option:
    return Option(provider=provider, provider_key=key, model=f"{key}-model")


async def ask(fallback: FallbackProvider) -> LLMReply:
    return await fallback.complete(messages=[Message(role=Role.USER, content="hi")], model="x")


# ------------------------------------------------------------ retry by failure


async def test_a_rate_limit_waits_and_tries_the_same_ai_again() -> None:
    ai = Scripted(ProviderRateLimitError("busy"), reply("ok"))
    clock = Clock()
    fallback = FallbackProvider([option(ai), option(Scripted(reply("b")), "b")], sleep=clock)

    result = await ask(fallback)

    assert result.text == "ok"
    assert ai.calls == 2
    assert clock.waits == [RATE_LIMIT_PAUSES[0]]
    assert fallback.index == 0  # never left the first AI


async def test_a_rate_limit_that_will_not_clear_moves_to_the_next_ai_after_two_retries() -> None:
    first = Scripted(ProviderRateLimitError("busy"))
    second = Scripted(reply("from b"))
    clock = Clock()
    switched: list[str] = []

    async def on_switch(old: Option, new: Option, exc: Exception) -> None:
        switched.append(new.provider_key)

    fallback = FallbackProvider(
        [option(first), option(second, "b")], on_switch=on_switch, sleep=clock
    )

    assert (await ask(fallback)).text == "from b"
    assert first.calls == 3  # the try and two retries
    assert clock.waits == list(RATE_LIMIT_PAUSES)
    assert switched == ["b"]


async def test_the_wait_the_vendor_asked_for_is_used_but_capped() -> None:
    ai = Scripted(ProviderRateLimitError("busy", retry_after=7), reply("ok"))
    clock = Clock()
    await ask(FallbackProvider([option(ai)], sleep=clock))
    assert clock.waits == [7.0]

    ai = Scripted(ProviderRateLimitError("busy", retry_after=3600), reply("ok"))
    clock = Clock()
    await ask(FallbackProvider([option(ai)], sleep=clock))
    assert clock.waits == [MAX_PAUSE_S]


async def test_an_outage_gets_one_quick_retry_then_the_next_ai() -> None:
    first = Scripted(ProviderUnavailableError("down"))
    clock = Clock()
    fallback = FallbackProvider([option(first), option(Scripted(reply("b")), "b")], sleep=clock)

    assert (await ask(fallback)).text == "b"
    assert first.calls == 2
    assert len(clock.waits) == 1


@pytest.mark.parametrize("error", [ProviderAuthError("bad key"), ProviderModelNotFoundError("no")])
async def test_a_refused_key_or_missing_model_moves_on_without_waiting(error: Exception) -> None:
    first = Scripted(error)
    clock = Clock()
    fallback = FallbackProvider([option(first), option(Scripted(reply("b")), "b")], sleep=clock)

    assert (await ask(fallback)).text == "b"
    assert first.calls == 1
    assert clock.waits == []


async def test_a_rejected_request_is_neither_retried_nor_sent_elsewhere() -> None:
    first = Scripted(ProviderRequestError("malformed"))
    second = Scripted(reply("b"))
    clock = Clock()
    fallback = FallbackProvider([option(first), option(second, "b")], sleep=clock)

    with pytest.raises(ProviderRequestError):
        await ask(fallback)
    assert first.calls == 1 and second.calls == 0 and clock.waits == []


async def test_with_one_ai_a_rate_limit_is_still_retried_and_then_raised() -> None:
    ai = Scripted(ProviderRateLimitError("busy"))
    clock = Clock()
    with pytest.raises(ProviderRateLimitError):
        await ask(FallbackProvider([option(ai)], sleep=clock))
    assert ai.calls == 3


async def test_each_retry_is_reported() -> None:
    seen: list[tuple[int, float]] = []

    async def on_retry(opt: Option, exc: Exception, attempt: int, delay: float) -> None:
        seen.append((attempt, delay))

    ai = Scripted(ProviderRateLimitError("busy"), ProviderRateLimitError("busy"), reply("ok"))
    await ask(FallbackProvider([option(ai)], on_retry=on_retry, sleep=Clock()))
    assert seen == [(1, RATE_LIMIT_PAUSES[0]), (2, RATE_LIMIT_PAUSES[1])]


def test_retry_after_is_read_from_a_plain_number_header_only() -> None:
    assert parse_retry_after({"retry-after": "12"}) == 12.0
    assert parse_retry_after({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}) is None
    assert parse_retry_after({}) is None
    assert parse_retry_after(None) is None


# ------------------------------------------------------------ escalation


def make_team(
    weak: LLMProvider, strong: LLMProvider | None, *, label_strong: str = "big:model"
) -> tuple[Team, list[tuple[str, dict]]]:
    events: list[tuple[str, dict]] = []

    async def emit(type_: str, **payload: Any) -> None:
        events.append((type_, payload))

    team = Team(
        provider=weak,
        model="weak-model",
        tools=[Calculator],
        check_policy=lambda name: ("auto", ""),
        emit=emit,
        provider_for=lambda role: (weak, "weak-model", "small:model"),
        escalate_for=(lambda role: (strong, "strong-model", label_strong)) if strong else None,
    )
    return team, events


def loops_forever() -> Scripted:
    """Never answers: asks the calculator every step until the step budget ends it."""
    call = ToolCall(id="c", name="calculator", arguments={"expression": "1+1"})
    return Scripted(reply(calls=[call]))


async def test_a_helper_that_runs_out_of_steps_is_retried_on_the_stronger_ai() -> None:
    team, events = make_team(loops_forever(), Scripted(reply("the real answer")))

    result = await run_specialist(team, ToolContext(owner_id=uuid.uuid4()), "analyst", "do it")

    assert result.ok and result.answer == "the real answer"
    kinds = [e[0] for e in events]
    assert kinds.count("specialist_started") == 1
    assert kinds.count("specialist_escalated") == 1
    escalated = next(p for t, p in events if t == "specialist_escalated")
    assert escalated["reason"] == "max_steps"
    assert escalated["model_from"] == "small:model" and escalated["model_to"] == "big:model"
    finished = next(p for t, p in events if t == "specialist_finished")
    assert finished["escalated"] is True and finished["ok"] is True


async def test_an_empty_answer_is_also_retried_on_the_stronger_ai() -> None:
    team, events = make_team(Scripted(reply("   ")), Scripted(reply("better")))
    result = await run_specialist(team, ToolContext(owner_id=uuid.uuid4()), "analyst", "do it")
    assert result.answer == "better"
    assert any(t == "specialist_escalated" for t, _ in events)


async def test_a_helper_that_finishes_is_not_escalated() -> None:
    strong = Scripted(reply("never used"))
    team, events = make_team(Scripted(reply("fine")), strong)
    result = await run_specialist(team, ToolContext(owner_id=uuid.uuid4()), "analyst", "do it")
    assert result.answer == "fine"
    assert strong.calls == 0
    assert not any(t == "specialist_escalated" for t, _ in events)


async def test_without_a_stronger_ai_the_failure_stands() -> None:
    team, events = make_team(loops_forever(), None)
    result = await run_specialist(team, ToolContext(owner_id=uuid.uuid4()), "analyst", "do it")
    assert not result.ok and result.stop_cause == "max_steps"
    assert not any(t == "specialist_escalated" for t, _ in events)


async def test_a_provider_outage_is_not_escalated() -> None:
    """The fallback has already tried every AI; a stronger one will not help."""
    strong = Scripted(reply("never used"))
    team, _ = make_team(Scripted(ProviderRequestError("bad")), strong)
    result = await run_specialist(team, ToolContext(owner_id=uuid.uuid4()), "analyst", "do it")
    assert not result.ok and strong.calls == 0


async def test_the_stronger_ai_gets_one_try_not_a_loop() -> None:
    strong = loops_forever()
    team, events = make_team(loops_forever(), strong)
    result = await run_specialist(team, ToolContext(owner_id=uuid.uuid4()), "analyst", "do it")
    assert not result.ok
    assert sum(1 for t, _ in events if t == "specialist_escalated") == 1


async def test_a_team_that_has_spent_its_budget_does_not_escalate() -> None:
    strong = Scripted(reply("never used"))
    team, _ = make_team(loops_forever(), strong)
    team.prompt_tokens = TEAM_TOKEN_BUDGET
    result = await run_specialist(team, ToolContext(owner_id=uuid.uuid4()), "analyst", "do it")
    assert not result.ok and strong.calls == 0


async def test_stronger_true_starts_on_the_stronger_ai_straight_away() -> None:
    weak = Scripted(reply("never used"))
    team, events = make_team(weak, Scripted(reply("strong first")))
    result = await run_specialist(
        team, ToolContext(owner_id=uuid.uuid4()), "writer", "do it", stronger=True
    )
    assert result.answer == "strong first" and weak.calls == 0
    started = next(p for t, p in events if t == "specialist_started")
    assert started["model"] == "big:model"


# ------------------------------------------------------------ per-helper numbers


async def test_each_helpers_cost_and_outcome_are_kept() -> None:
    team, _ = make_team(Scripted(reply("one")), None)
    ctx = ToolContext(owner_id=uuid.uuid4())
    await run_specialist(team, ctx, "analyst", "a")
    await run_specialist(team, ctx, "analyst", "b")
    await run_specialist(team, ctx, "critic", "c")

    summary = team.summary()
    analyst = summary["roles"]["analyst"]
    assert analyst["calls"] == 2 and analyst["finished"] == 2 and analyst["escalated"] == 0
    assert analyst["prompt_tokens"] == 20 and analyst["output_tokens"] == 10
    assert analyst["models"] == ["small:model", "small:model"]
    assert summary["roles"]["critic"]["calls"] == 1
    assert summary["cost_usd"] >= 0


async def test_an_escalated_helper_is_counted_once_with_both_attempts_costed() -> None:
    team, _ = make_team(loops_forever(), Scripted(reply("ok")))
    await run_specialist(team, ToolContext(owner_id=uuid.uuid4()), "analyst", "do it")

    row = team.summary()["roles"]["analyst"]
    assert row["calls"] == 1 and row["finished"] == 1 and row["escalated"] == 1
    assert row["models"] == ["small:model", "big:model"]
    assert row["steps"] > 1  # the failed try's steps count too
    assert row["prompt_tokens"] == team.prompt_tokens  # nothing lost between the two
