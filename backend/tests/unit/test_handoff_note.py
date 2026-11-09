"""When one AI stops part way and another takes over, the new one is told
what is already done, and each AI's work and usage is tracked.

All offline: scripted providers stand in for the real ones, so what each AI
was sent can be checked exactly.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import BaseModel

from app.agent.loop import AgentEvent, AgentLoop, RunOutcome
from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    ProviderAuthError,
    ProviderRateLimitError,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from app.agent.providers.fallback import FallbackProvider, Option
from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.packs.calculator import Calculator
from app.agent.worklog import (
    MARKER,
    MAX_LISTED,
    WorkLog,
    attach_note,
    build_note,
    reason_for,
    with_note,
)

# ------------------------------------------------------------------ helpers


class Capture(LLMProvider):
    """Plays each item in turn (a reply, or an error to raise) and records
    exactly what it was sent."""

    provider_key = "capture"

    def __init__(self, *items: Any) -> None:
        super().__init__(api_key="x")
        self.items = list(items)
        self.calls: list[list[Message]] = []

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        self.calls.append(list(kwargs["messages"]))
        item = self.items[min(len(self.calls) - 1, len(self.items) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    async def check(self, model: str) -> None:
        return None

    def system(self, call: int) -> str:
        return next(m.content or "" for m in self.calls[call] if m.role is Role.SYSTEM)


def answer(text: str, tokens: tuple[int, int] = (10, 5)) -> LLMReply:
    return LLMReply(
        message=Message(role=Role.ASSISTANT, content=text),
        stop_reason=StopReason.END_TURN,
        usage=Usage(*tokens),
        model="m",
    )


def step(call_id: str, name: str, tokens: tuple[int, int] = (10, 5), **arguments: Any) -> LLMReply:
    return LLMReply(
        message=Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        ),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(*tokens),
        model="m",
    )


class RowArgs(BaseModel):
    sheet: str = "Invoices"


class AddRow(Tool):
    """A change. Not in the registry, so it is treated as a change."""

    name = "add_row"
    pack = "test"
    description = "Add a row to a sheet."
    args_model = RowArgs
    side_effect = SideEffect.WRITE

    async def run(self, ctx: ToolContext, args: RowArgs) -> ToolResult:  # type: ignore[override]
        return ToolResult.success("row added")


class SendMail(Tool):
    name = "send_mail"
    pack = "test"
    description = "Send an email."
    args_model = RowArgs
    side_effect = SideEffect.DESTRUCTIVE

    async def run(self, ctx: ToolContext, args: RowArgs) -> ToolResult:  # type: ignore[override]
        raise RuntimeError("boom")


class Clock:
    async def __call__(self, seconds: float) -> None:
        return None


def option(provider: LLMProvider, key: str) -> Option:
    return Option(provider=provider, provider_key=key, model=f"{key}-model")


async def run_loop(
    first: Capture, *others: Capture, tools: list[type[Tool]] | None = None
) -> tuple[RunOutcome, FallbackProvider]:
    options = [option(first, "a"), *(option(p, k) for p, k in zip(others, "bcd", strict=False))]
    provider = FallbackProvider(options, sleep=Clock())
    loop = AgentLoop(
        provider=provider,
        model="a-model",
        tools=tools if tools is not None else [AddRow, Calculator, SendMail],
        tool_context=ToolContext(owner_id=uuid.uuid4()),
    )
    outcome = await loop.run(system_prompt="You are Baton.", task="Do the five jobs.")
    return outcome, provider


def events(outcome: RunOutcome, kind: str) -> list[AgentEvent]:
    return [e for e in outcome.events if e.type == kind]


# --------------------------------------------------- the note reaches the AI


async def test_the_ai_that_takes_over_is_told_what_is_already_done() -> None:
    a = Capture(
        step("c1", "add_row", sheet="Invoices"),
        step("c2", "calculator", expression="12+30"),
        ProviderAuthError("key refused"),
    )
    b = Capture(answer("All done."))

    outcome, _ = await run_loop(a, b)

    assert outcome.completed and outcome.output == "All done."
    told = b.system(0)
    assert MARKER in told
    assert "You are Baton." in told  # the original instructions are kept
    done_part, _, looked_part = told.partition("Already looked up")
    assert "Do NOT repeat" in done_part and "add_row" in done_part
    assert "calculator" in looked_part and "add_row" not in looked_part
    assert "[a:a-model]" in told  # who did each step
    assert "its key was refused" in told  # why the first AI stopped


async def test_the_first_ai_is_not_given_a_note() -> None:
    a = Capture(step("c1", "add_row"), ProviderAuthError("key refused"))
    b = Capture(answer("ok"))

    await run_loop(a, b)

    assert all(MARKER not in a.system(i) for i in range(len(a.calls)))


async def test_the_note_stays_for_every_later_step_of_the_new_ai() -> None:
    a = Capture(step("c1", "add_row"), ProviderAuthError("limit"))
    b = Capture(step("c3", "calculator", expression="1+1"), answer("fine"))

    await run_loop(a, b)

    assert len(b.calls) == 2
    for i in range(2):
        assert b.system(i).count(MARKER) == 1
    # and what B did itself is in the list it sends next time
    assert any(m.role is Role.TOOL and m.tool_call_id == "c3" for m in b.calls[1])


async def test_a_second_handoff_replaces_the_note_instead_of_stacking_it() -> None:
    a = Capture(step("c1", "add_row"), ProviderAuthError("x"))
    b = Capture(step("c2", "calculator", expression="2+2"), ProviderAuthError("y"))
    c = Capture(answer("finished"))

    outcome, _ = await run_loop(a, b, c)

    assert outcome.completed
    told = c.system(0)
    assert told.count(MARKER) == 1
    assert "add_row" in told and "calculator" in told
    assert "(b:b-model)" in told  # the AI that stopped last
    assert len(events(outcome, "handoff_note")) == 2


async def test_no_note_when_the_ai_stops_before_any_step_is_finished() -> None:
    a = Capture(ProviderAuthError("key refused"))
    b = Capture(answer("ok"))

    outcome, _ = await run_loop(a, b)

    assert MARKER not in b.system(0)
    assert events(outcome, "handoff_note") == []


async def test_a_failed_step_is_listed_as_failed_not_as_done() -> None:
    a = Capture(step("c1", "send_mail"), ProviderAuthError("x"))
    b = Capture(answer("ok"))

    outcome, _ = await run_loop(a, b)

    told = b.system(0)
    assert "Tried and failed" in told and "send_mail" in told and "boom" in told
    assert "Do NOT repeat" not in told
    (note,) = events(outcome, "handoff_note")
    assert (note.payload["done"], note.payload["failed"]) == (0, 1)


async def test_without_a_switch_there_is_no_note_and_one_ai_is_tracked() -> None:
    a = Capture(step("c1", "add_row"), answer("ok"))

    outcome, _ = await run_loop(a, Capture(answer("unused")))

    assert all(MARKER not in a.system(i) for i in range(len(a.calls)))
    assert events(outcome, "handoff_note") == []
    assert list(outcome.model_usage) == ["a:a-model"]


async def test_a_rate_limited_ai_is_retried_and_only_then_handed_over() -> None:
    a = Capture(step("c1", "add_row"), ProviderRateLimitError("busy"))
    b = Capture(answer("ok"))

    outcome, _ = await run_loop(a, b)

    assert len(a.calls) == 4  # the first step, then the try and two retries
    (note,) = events(outcome, "handoff_note")
    assert note.payload["reason"] == "it reached its usage limit"


# ------------------------------------------------------------ usage tracking


async def test_each_ais_calls_tokens_and_steps_are_tracked() -> None:
    a = Capture(
        step("c1", "add_row", tokens=(100, 20)),
        step("c2", "calculator", tokens=(150, 30), expression="1+1"),
        ProviderAuthError("limit"),
    )
    b = Capture(answer("done", tokens=(200, 40)))

    outcome, _ = await run_loop(a, b)

    assert outcome.model_usage == {
        "a:a-model": {"calls": 2, "prompt_tokens": 250, "output_tokens": 50, "tool_calls": 2},
        "b:b-model": {"calls": 1, "prompt_tokens": 200, "output_tokens": 40, "tool_calls": 0},
    }


async def test_the_handoff_event_says_who_why_and_how_much_was_done() -> None:
    a = Capture(step("c1", "add_row"), step("c2", "calculator", expression="1+1"))
    a.items.append(ProviderAuthError("limit"))
    b = Capture(answer("ok"))

    outcome, _ = await run_loop(a, b)

    (note,) = events(outcome, "handoff_note")
    payload = note.payload
    assert payload["from_model"] == "a:a-model" and payload["to_model"] == "b:b-model"
    assert (payload["done"], payload["looked_up"], payload["failed"]) == (1, 1, 0)
    assert payload["usage"]["a:a-model"]["tool_calls"] == 2


# -------------------------------------------------------- the note, directly


def conversation(count: int) -> tuple[list[Message], WorkLog]:
    log = WorkLog()
    messages = [Message(role=Role.SYSTEM, content="sys"), Message(role=Role.USER, content="go")]
    for n in range(count):
        call = ToolCall(id=f"c{n}", name="add_row", arguments={"sheet": f"s{n}"})
        messages.append(Message(role=Role.ASSISTANT, tool_calls=[call]))
        messages.append(Message(role=Role.TOOL, content="row added", tool_call_id=call.id))
        log.made_by[call.id] = "a:a-model"
    return messages, log


def test_a_long_list_is_capped_and_says_how_many_were_left_out() -> None:
    messages, log = conversation(MAX_LISTED + 5)

    note = build_note(messages, log)

    assert note is not None
    assert note.done == MAX_LISTED and note.omitted == 5
    assert "5 earlier steps are not listed" in note.text
    assert "s24" in note.text and "s0 " not in note.text  # newest kept, oldest cut


def test_a_call_that_never_got_a_result_is_not_called_done() -> None:
    messages, log = conversation(1)
    pending = ToolCall(id="late", name="add_row", arguments={"sheet": "later"})
    messages.append(Message(role=Role.ASSISTANT, tool_calls=[pending]))

    note = build_note(messages, log)

    assert note is not None and "later" not in note.text


def test_a_step_the_person_blocked_is_listed_as_failed() -> None:
    messages, log = conversation(0)
    call = ToolCall(id="c9", name="send_mail", arguments={})
    messages.append(Message(role=Role.ASSISTANT, tool_calls=[call]))
    messages.append(
        Message(
            role=Role.TOOL,
            content="'send_mail' is not permitted (blocked). Do not try it again.",
            tool_call_id="c9",
        )
    )

    note = build_note(messages, log)

    assert (
        note is not None and note.failed == 1 and "blocked by the person's permissions" in note.text
    )


def test_long_arguments_are_cut_short() -> None:
    messages, log = conversation(0)
    call = ToolCall(id="c1", name="add_row", arguments={"sheet": "x" * 500})
    messages += [
        Message(role=Role.ASSISTANT, tool_calls=[call]),
        Message(role=Role.TOOL, content="ok", tool_call_id="c1"),
    ]

    note = build_note(messages, log)

    assert note is not None and "x" * 200 not in note.text


def test_the_note_goes_into_the_instructions_and_a_new_one_replaces_it() -> None:
    messages = [
        Message(role=Role.SYSTEM, content="Be helpful."),
        Message(role=Role.USER, content="hi"),
    ]

    once = with_note(messages, f"{MARKER}\nfirst")
    twice = with_note(once, f"{MARKER}\nsecond")

    assert messages[0].content == "Be helpful."  # the original is not changed
    assert twice[0].content is not None
    assert twice[0].content.startswith("Be helpful.")
    assert "second" in twice[0].content and "first" not in twice[0].content
    assert twice[1].content == "hi"


def test_a_list_with_no_instructions_gets_them_added() -> None:
    messages = [Message(role=Role.USER, content="hi")]

    attach_note(messages, f"{MARKER}\nnote")

    assert messages[0].role is Role.SYSTEM and "note" in (messages[0].content or "")
    assert len(messages) == 2


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (ProviderRateLimitError("x"), "usage limit"),
        (ProviderAuthError("x"), "key was refused"),
    ],
)
def test_the_reason_is_in_plain_words(error: Exception, words: str) -> None:
    assert words in reason_for(error)  # type: ignore[arg-type]


async def test_outside_an_agent_loop_a_switch_adds_no_note() -> None:
    """A provider used on its own (not inside a loop) has no record of work."""
    a = Capture(ProviderAuthError("x"))
    b = Capture(answer("ok"))
    fallback = FallbackProvider([option(a, "a"), option(b, "b")], sleep=Clock())

    reply = await fallback.complete(
        messages=[Message(role=Role.SYSTEM, content="sys"), Message(role=Role.USER, content="hi")],
        model="x",
    )

    assert reply.handoff is None and MARKER not in b.system(0)
