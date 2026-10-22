"""Automatic routing: what kind of task, which AI, and falling back."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    ProviderRateLimitError,
    ProviderRequestError,
    Role,
    StopReason,
    Usage,
)
from app.agent.providers.fallback import FallbackProvider, Option
from app.agent.routing import (
    Candidate,
    Preference,
    TaskKind,
    classify_by_rules,
    parse_kind,
    rank,
    strengths,
)

CLAUDE = Candidate("anthropic", "claude-opus-5-5", "Claude")
GEMINI = Candidate("gemini", "gemini-2.5-flash", "Gemini")
GROQ = Candidate("groq", "openai/gpt-oss-20b", "Groq")
OWN = Candidate("custom", "llama-3.3-70b", "Our server")
ALL = [CLAUDE, GEMINI, GROQ, OWN]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Fix this ```python\nprint(x)```", TaskKind.CODING),
        ("Why does my SQL query return duplicates?", TaskKind.CODING),
        ("Fix this NameError: total += price says total is not defined", TaskKind.CODING),
        ("Draft a polite email to my landlord about the leak", TaskKind.WRITING),
        ("Compare RAG and fine-tuning: pros and cons", TaskKind.ANALYSIS),
        ("Check my inbox for unpaid invoices", TaskKind.TOOLS),
        ("What is the capital of Peru?", TaskKind.QUICK),
        ("x " * 4000, TaskKind.LONG),
        ("Thoughts on my weekend?", None),  # not sure: ask a cheap AI
    ],
)
def test_rules_decide_most_tasks(text: str, kind: TaskKind | None) -> None:
    assert classify_by_rules(text) == kind


def test_a_long_conversation_counts_as_long_work() -> None:
    assert classify_by_rules("And the next chapter?", history_chars=50_000) is TaskKind.LONG


def test_balanced_sends_hard_work_to_the_strongest_and_easy_work_to_the_cheapest() -> None:
    assert rank(ALL, TaskKind.CODING, Preference.BALANCED)[0] == CLAUDE
    assert rank(ALL, TaskKind.ANALYSIS, Preference.BALANCED)[0] == CLAUDE
    assert rank(ALL, TaskKind.QUICK, Preference.BALANCED)[0] != CLAUDE
    assert rank(ALL, TaskKind.LONG, Preference.BALANCED)[0] == GEMINI


def test_each_preference_means_what_it_says() -> None:
    assert rank(ALL, TaskKind.QUICK, Preference.QUALITY)[0] == CLAUDE
    assert rank(ALL, TaskKind.CODING, Preference.COST)[0] != CLAUDE
    assert rank(ALL, TaskKind.CODING, Preference.PRIVATE) == [OWN]
    assert rank([CLAUDE, GEMINI], TaskKind.CODING, Preference.PRIVATE) == []


def test_a_connection_that_failed_its_test_is_tried_last() -> None:
    broken = Candidate("anthropic", "claude-opus-5-5", "Claude", failed=True)
    assert rank([broken, GEMINI], TaskKind.CODING, Preference.QUALITY)[-1] == broken


def test_an_unknown_model_still_ranks() -> None:
    odd = Candidate("openrouter", "someone/brand-new-model", "OpenRouter")
    assert rank([odd], TaskKind.WRITING, Preference.BALANCED) == [odd]


def test_the_ai_classifier_answer_is_read_forgivingly() -> None:
    assert parse_kind("Coding.") is TaskKind.CODING
    assert parse_kind("  analysis\n") is TaskKind.ANALYSIS
    assert parse_kind("I think it's a poem") is TaskKind.GENERAL
    assert parse_kind(None) is TaskKind.GENERAL


def test_strengths_are_plain_words() -> None:
    assert "coding" in strengths("anthropic", "claude-opus-5-5")
    assert "very fast" in strengths("groq", "openai/gpt-oss-20b")
    assert "private" in strengths("custom", "anything")


class Scripted(LLMProvider):
    provider_key = "x"

    def __init__(self, name: str, error: Exception | None = None) -> None:
        super().__init__(name)
        self.error = error
        self.calls = 0

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        self.calls += 1
        if self.error:
            raise self.error
        return LLMReply(
            message=Message(role=Role.ASSISTANT, content=f"{self.api_key}:{kwargs['model']}"),
            stop_reason=StopReason.END_TURN,
            usage=Usage(1, 1),
            model=kwargs["model"],
        )

    async def check(self, model: str) -> None:
        return None


async def test_fallback_moves_on_when_an_ai_is_rate_limited() -> None:
    switched: list[str] = []

    async def on_switch(old: Option, new: Option, exc: Exception) -> None:
        switched.append(f"{old.provider_key}->{new.provider_key}")

    busy = Scripted("claude", ProviderRateLimitError("slow down"))
    spare = Scripted("gemini")
    provider = FallbackProvider(
        [Option(busy, "anthropic", "opus"), Option(spare, "gemini", "flash")], on_switch=on_switch
    )

    reply = await provider.complete(messages=[], model="ignored")
    assert reply.text == "gemini:flash"  # each option uses its own model
    assert switched == ["anthropic->gemini"]
    assert provider.current.provider_key == "gemini"

    await provider.complete(messages=[], model="ignored")
    # It was tried again twice after the rate limit (waiting each time) before
    # the switch, and then it is left alone: the AI that works keeps the run.
    assert busy.calls == 3


async def test_fallback_does_not_retry_a_request_every_ai_would_reject() -> None:
    bad = Scripted("claude", ProviderRequestError("malformed"))
    spare = Scripted("gemini")
    provider = FallbackProvider(
        [Option(bad, "anthropic", "opus"), Option(spare, "gemini", "flash")]
    )
    with pytest.raises(ProviderRequestError):
        await provider.complete(messages=[], model="ignored")
    assert spare.calls == 0
