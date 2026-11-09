"""An AI that just failed rests for a while, so the next run goes straight to
one that works. Offline: the marks are held in this process during tests."""

from __future__ import annotations

import uuid

import pytest

from app.agent import cooldown
from app.agent.cooldown import (
    KEY_PROBLEM_S,
    OUTAGE_BASE_S,
    OUTAGE_CAP_S,
    RATE_LIMIT_BASE_S,
    RATE_LIMIT_CAP_S,
    plan,
)
from app.agent.providers.base import (
    ProviderAuthError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTooLargeError,
    ProviderUnavailableError,
)
from app.agent.routing import Candidate, Preference, TaskKind, rank

PERSON = uuid.uuid4()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# ------------------------------------------------------------ how long it rests


def test_a_usage_limit_rests_a_minute_and_doubles_each_time_up_to_a_cap() -> None:
    seconds = [plan(ProviderRateLimitError("busy"), n).seconds for n in (1, 2, 3, 4, 5, 6)]  # type: ignore[union-attr]
    assert seconds == [60, 120, 240, 480, 900, 900]
    assert seconds[0] == RATE_LIMIT_BASE_S and seconds[-1] == RATE_LIMIT_CAP_S


def test_the_wait_the_vendor_asked_for_is_used_when_it_is_longer() -> None:
    long_ask = plan(ProviderRateLimitError("busy", retry_after=300), 1)
    short_ask = plan(ProviderRateLimitError("busy", retry_after=3), 1)
    absurd = plan(ProviderRateLimitError("busy", retry_after=86_400), 1)
    assert long_ask is not None and long_ask.seconds == 300
    assert short_ask is not None and short_ask.seconds == RATE_LIMIT_BASE_S
    assert absurd is not None and absurd.seconds == RATE_LIMIT_CAP_S


def test_an_outage_rests_briefly_and_never_for_long() -> None:
    seconds = [plan(ProviderUnavailableError("down"), n).seconds for n in (1, 2, 3, 4, 5, 6)]  # type: ignore[union-attr]
    assert seconds == [30, 60, 120, 240, 300, 300]
    assert seconds[0] == OUTAGE_BASE_S and seconds[-1] == OUTAGE_CAP_S


@pytest.mark.parametrize("error", [ProviderAuthError("x"), ProviderModelNotFoundError("x")])
def test_a_refused_key_or_missing_model_rests_long_because_waiting_does_not_fix_it(
    error: Exception,
) -> None:
    decided = plan(error, 1)  # type: ignore[arg-type]
    assert decided is not None and decided.seconds == KEY_PROBLEM_S
    assert plan(error, 5).seconds == KEY_PROBLEM_S  # type: ignore[arg-type, union-attr]


@pytest.mark.parametrize("error", [ProviderTooLargeError("big"), ProviderRequestError("malformed")])
def test_a_request_problem_says_nothing_about_the_ai(error: Exception) -> None:
    assert plan(error, 1) is None  # type: ignore[arg-type]


# --------------------------------------------------------------- remembering it


async def test_an_ai_that_failed_is_resting_for_everyone_using_the_same_key() -> None:
    await cooldown.rest(PERSON, "gemini", ProviderRateLimitError("busy"))

    resting = await cooldown.resting(PERSON, ["gemini", "groq"])

    assert resting == {"gemini": "reached its usage limit"}


async def test_one_persons_rest_does_not_touch_another_persons_ai() -> None:
    await cooldown.rest(PERSON, "gemini", ProviderRateLimitError("busy"))

    assert await cooldown.resting(uuid.uuid4(), ["gemini"]) == {}


async def test_the_rest_ends_by_itself() -> None:
    clock = Clock()
    cooldown._memory.clock = clock
    await cooldown.rest(PERSON, "gemini", ProviderRateLimitError("busy"))

    clock.now += RATE_LIMIT_BASE_S - 1
    assert "gemini" in await cooldown.resting(PERSON, ["gemini"])
    clock.now += 2
    assert await cooldown.resting(PERSON, ["gemini"]) == {}


async def test_failing_again_soon_rests_longer_and_a_quiet_hour_forgives() -> None:
    clock = Clock()
    cooldown._memory.clock = clock

    first = await cooldown.rest(PERSON, "gemini", ProviderRateLimitError("busy"))
    clock.now += 61  # the first rest is over
    second = await cooldown.rest(PERSON, "gemini", ProviderRateLimitError("busy"))
    assert (first.seconds, second.seconds) == (60, 120)  # type: ignore[union-attr]

    clock.now += cooldown.STRIKE_WINDOW_S + 1  # an hour with no trouble
    third = await cooldown.rest(PERSON, "gemini", ProviderRateLimitError("busy"))
    assert third.seconds == 60  # type: ignore[union-attr]


async def test_a_working_ai_ends_its_rest_and_its_strikes() -> None:
    await cooldown.rest(PERSON, "gemini", ProviderRateLimitError("busy"))
    await cooldown.rest(PERSON, "gemini", ProviderRateLimitError("busy"))

    await cooldown.recovered(PERSON, "gemini")

    assert await cooldown.resting(PERSON, ["gemini"]) == {}
    again = await cooldown.rest(PERSON, "gemini", ProviderRateLimitError("busy"))
    assert again.seconds == 60  # type: ignore[union-attr]  # strikes started over


async def test_a_too_big_request_earns_no_rest_and_no_strike() -> None:
    assert await cooldown.rest(PERSON, "groq", ProviderTooLargeError("big")) is None
    assert await cooldown.resting(PERSON, ["groq"]) == {}

    first_real = await cooldown.rest(PERSON, "groq", ProviderRateLimitError("busy"))
    assert first_real.seconds == 60  # type: ignore[union-attr]  # not doubled by the big one


async def test_nothing_to_look_up_is_fine() -> None:
    assert await cooldown.resting(PERSON, []) == {}


# ------------------------------------------------------------------- routing


def _candidates(*cooling: str) -> list[Candidate]:
    return [
        Candidate(
            "anthropic",
            "claude-opus-5-5",
            "Claude",
            cooling="usage limit" if "anthropic" in cooling else None,
        ),
        Candidate(
            "gemini",
            "gemini-2.0-flash",
            "Gemini",
            cooling="usage limit" if "gemini" in cooling else None,
        ),
    ]


def test_a_resting_ai_goes_last_even_when_it_is_the_best_fit() -> None:
    usual = rank(_candidates(), TaskKind.CODING, Preference.BALANCED)
    assert usual[0].provider_key == "anthropic"

    ranked = rank(_candidates("anthropic"), TaskKind.CODING, Preference.BALANCED)

    assert [c.provider_key for c in ranked] == [
        "gemini",
        "anthropic",
    ]  # still there, as a last resort


def test_when_every_ai_is_resting_the_usual_order_applies() -> None:
    ranked = rank(_candidates("anthropic", "gemini"), TaskKind.CODING, Preference.BALANCED)
    assert ranked[0].provider_key == "anthropic"
    assert len(ranked) == 2
