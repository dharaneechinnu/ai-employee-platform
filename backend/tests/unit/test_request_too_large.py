"""An AI that says the request is too big: switch AI first, then send a slimmer one.

Seen with a free-tier Groq key: a 10,620 token request against an 8,000
tokens-per-minute limit came back as HTTP 413 and failed the run, because
it was neither a rate limit (retried) nor retryable anywhere else.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from app.agent.loop import AgentLoop
from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    ProviderRequestError,
    ProviderTooLargeError,
    Role,
    StopReason,
    ToolCall,
    ToolSchema,
    Usage,
    too_large_error,
)
from app.agent.providers.fallback import FallbackProvider, Option
from app.agent.providers.openai_compatible import OpenAICompatibleProvider
from app.agent.slim import (
    TOOL_DESCRIPTION_CHARS,
    TOOL_RESULT_CHARS,
    estimate_tokens,
    slim_messages,
    slim_tools,
)
from app.agent.tools.base import ToolContext

GROQ_413 = (
    '{"error":{"message":"Request too large for model `openai/gpt-oss-20b` in organization '
    "`org_x` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Requested 10620, "
    'please reduce your message size and try again.","type":"tokens","code":"rate_limit_exceeded"}}'
)


def _answer(text: str) -> LLMReply:
    return LLMReply(
        message=Message(role=Role.ASSISTANT, content=text),
        stop_reason=StopReason.END_TURN,
        usage=Usage(10, 5),
        model="m",
    )


# ------------------------------------------------------------ recognising it


def test_groqs_413_becomes_a_too_large_error_with_its_numbers() -> None:
    error = too_large_error("groq", 413, GROQ_413)

    assert isinstance(error, ProviderTooLargeError)
    assert (error.limit_tokens, error.requested_tokens) == (8000, 10620)
    assert "10620" in error.message and "8000" in error.message


@pytest.mark.parametrize("status", [400, 429])
def test_the_wording_alone_is_enough_whatever_the_status(status: int) -> None:
    assert too_large_error("groq", status, GROQ_413) is not None


def test_an_ordinary_rejection_is_not_mistaken_for_it() -> None:
    assert (
        too_large_error("groq", 400, '{"error":{"message":"messages must not be empty"}}') is None
    )
    assert too_large_error("groq", 429, '{"error":{"message":"Rate limit reached"}}') is None


@pytest.mark.parametrize(
    "response",
    [httpx.Response(413, text=GROQ_413), httpx.Response(429, text=GROQ_413)],
)
def test_the_openai_compatible_adapter_raises_it(response: httpx.Response) -> None:
    provider = OpenAICompatibleProvider("k", provider_key="groq")
    with pytest.raises(ProviderTooLargeError):
        provider._raise_for_status(response)


def test_another_bad_request_is_still_a_plain_request_error() -> None:
    provider = OpenAICompatibleProvider("k", provider_key="groq")
    with pytest.raises(ProviderRequestError):
        provider._raise_for_status(httpx.Response(400, text='{"error":{"message":"bad json"}}'))


# ------------------------------------------------------- option 1: switch AI


class Scripted(LLMProvider):
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


def _option(provider: LLMProvider, key: str) -> Option:
    return Option(provider=provider, provider_key=key, model=f"{key}-model")


async def test_a_too_large_request_goes_to_the_next_ai_without_waiting() -> None:
    small = Scripted(ProviderTooLargeError("too big", limit_tokens=8000, requested_tokens=10620))
    big = Scripted(_answer("from the bigger AI"))
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    fallback = FallbackProvider([_option(small, "groq"), _option(big, "gemini")], sleep=sleep)
    reply = await fallback.complete(messages=[Message(role=Role.USER, content="hi")], model="x")

    assert reply.text == "from the bigger AI"
    assert small.calls == 1  # not retried: waiting cannot make it smaller
    assert waits == []
    assert fallback.current.provider_key == "gemini"


async def test_with_no_other_ai_the_error_goes_up_to_the_loop() -> None:
    only = Scripted(ProviderTooLargeError("too big"))
    fallback = FallbackProvider([_option(only, "groq")])
    with pytest.raises(ProviderTooLargeError):
        await fallback.complete(messages=[Message(role=Role.USER, content="hi")], model="x")
    assert only.calls == 1


# ------------------------------------------------------ option 2: slim it


def _tool(name: str, description: str) -> ToolSchema:
    return ToolSchema(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "title": "Args",
            "properties": {
                "query": {"type": "string", "title": "Query", "description": "x" * 300},
                "description": {"type": "string", "description": "A field named description."},
                "mode": {"type": "string", "enum": ["a", "b"]},
            },
            "required": ["query"],
        },
    )


def test_slimmed_tools_keep_what_makes_a_call_valid() -> None:
    long = "Search the web. " + "More detail about how to use this tool. " * 20
    [slim] = slim_tools([_tool("web_search", long)])

    assert slim.name == "web_search"
    assert slim.description == "Search the web."
    props = slim.parameters["properties"]
    assert set(props) == {"query", "description", "mode"}  # a field called description survives
    assert props["mode"]["enum"] == ["a", "b"]
    assert slim.parameters["required"] == ["query"]
    assert "title" not in slim.parameters and "title" not in props["query"]
    assert len(props["query"]["description"]) <= 60


def test_a_description_with_no_full_stop_is_cut_to_a_limit() -> None:
    [slim] = slim_tools([_tool("t", "word " * 200)])
    assert len(slim.description) <= TOOL_DESCRIPTION_CHARS


def _chat() -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content="You are a helper."),
        Message(role=Role.USER, content="old question"),
        Message(role=Role.ASSISTANT, content="old answer"),
        Message(role=Role.USER, content="new question"),
        Message(
            role=Role.ASSISTANT, tool_calls=[ToolCall(id="c1", name="web_search", arguments={})]
        ),
        Message(role=Role.TOOL, content="r" * 5000, tool_call_id="c1", name="web_search"),
    ]


def test_level_one_leaves_the_messages_alone() -> None:
    messages = _chat()
    assert slim_messages(messages, 1) is messages


def test_level_two_drops_earlier_turns_but_keeps_this_request_and_its_tool_calls() -> None:
    kept = slim_messages(_chat(), 2)

    assert [m.role for m in kept] == [Role.SYSTEM, Role.USER, Role.ASSISTANT, Role.TOOL]
    assert kept[1].content == "new question"
    assert kept[3].content == "r" * 5000  # results are untouched until level three


def test_level_three_also_shortens_long_tool_results() -> None:
    kept = slim_messages(_chat(), 3)
    assert len(kept[-1].content or "") < TOOL_RESULT_CHARS + 20
    assert kept[-1].tool_call_id == "c1"  # still answers its call


def test_slimming_never_changes_the_real_conversation() -> None:
    messages = _chat()
    slim_messages(messages, 3)
    assert len(messages) == 6 and len(messages[-1].content or "") == 5000


def test_each_level_is_smaller_than_the_last() -> None:
    tools = [_tool(f"t{i}", "Does a thing. " * 30) for i in range(10)]
    sizes = [
        estimate_tokens(slim_messages(_chat(), lvl), tools if lvl < 1 else slim_tools(tools))
        for lvl in range(4)
    ]
    assert sizes == sorted(sizes, reverse=True) and sizes[0] > sizes[-1]


# ------------------------------------------------- the loop uses them


class SmallLimitProvider(LLMProvider):
    """Refuses any request over `limit` estimated tokens, as a free tier does."""

    provider_key = "small"

    def __init__(self, limit: int) -> None:
        super().__init__(api_key="x")
        self.limit = limit
        self.sizes: list[int] = []

    async def complete(  # type: ignore[override]
        self,
        *,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMReply:
        size = estimate_tokens(messages, tools)
        self.sizes.append(size)
        if size > self.limit:
            raise ProviderTooLargeError(
                "too big", status_code=413, limit_tokens=self.limit, requested_tokens=size
            )
        return _answer("done")

    async def check(self, model: str) -> None:
        return None


def _loop(provider: LLMProvider, events: list[Any]) -> AgentLoop:
    from tests.unit.test_agent_loop import EchoTool

    async def sink(event: Any) -> None:
        events.append(event)

    return AgentLoop(
        provider=provider,
        model="m",
        tools=[EchoTool],
        tool_context=ToolContext(owner_id=uuid.uuid4()),
        on_event=sink,
    )


async def test_the_run_sends_a_slimmer_request_instead_of_failing() -> None:
    history = [
        Message(role=Role.USER, content="q " * 4000),
        Message(role=Role.ASSISTANT, content="a " * 4000),
    ]
    provider = SmallLimitProvider(limit=1500)
    events: list[Any] = []

    outcome = await _loop(provider, events).run(
        system_prompt="sys", task="new question", history=history
    )

    assert outcome.completed and outcome.output == "done"
    slimmed = [e for e in events if e.type == "request_slimmed"]
    assert [e.payload["level"] for e in slimmed] == [1, 2]  # stopped once it fit
    assert (
        slimmed[-1].payload["estimated_tokens_after"]
        < slimmed[0].payload["estimated_tokens_before"]
    )
    assert provider.sizes[0] > 1500 >= provider.sizes[-1]


async def test_a_request_that_still_will_not_fit_fails_with_the_providers_reason() -> None:
    provider = SmallLimitProvider(limit=1)
    events: list[Any] = []

    outcome = await _loop(provider, events).run(system_prompt="sys", task="hello")

    assert outcome.stop_cause == "provider_error"
    assert [e.payload["level"] for e in events if e.type == "request_slimmed"] == [1, 2, 3]


async def test_a_run_that_fits_is_never_slimmed() -> None:
    events: list[Any] = []
    outcome = await _loop(SmallLimitProvider(limit=10_000), events).run(
        system_prompt="sys", task="hello"
    )
    assert outcome.completed
    assert not [e for e in events if e.type == "request_slimmed"]


def test_old_tool_results_are_cut_but_the_newest_stay_whole() -> None:
    from app.agent.slim import OLD_RESULT_CHARS, compact_old_results

    big = "x" * (OLD_RESULT_CHARS * 3)
    messages = [
        Message(role=Role.USER, content="go"),
        Message(role=Role.ASSISTANT, content=""),
        Message(role=Role.TOOL, content=big, tool_call_id="1", name="get_webpage"),
        Message(role=Role.ASSISTANT, content=""),
        Message(role=Role.TOOL, content=big, tool_call_id="2", name="get_webpage"),
    ]
    out = compact_old_results(messages)
    assert len(out[2].content) < len(big)
    assert out[4].content == big
    assert messages[2].content == big  # the real conversation is untouched
