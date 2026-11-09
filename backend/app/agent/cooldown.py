"""A short rest for an AI that just failed, shared by everything a person runs.

A person's agents all use the same keys, and the same limits. Without this,
every run finds a limit for itself: it waits 2 seconds, then 5, and only
then moves to the next AI. With twenty agents that is twenty runs wasting
the same seven seconds, and all of them hammering a key that is already
over its limit.

So when a run has to give up on an AI, it is marked as resting, and
routing puts it last for a while. The next run goes straight to an AI that
is working. Nothing is blocked: a resting AI is still tried when no other
is left, and a person who pinned one AI is never rerouted.

How long it rests depends on what went wrong:

- Usage limit: a minute, doubling each time it happens again within the
  hour, up to 15 minutes. The wait the vendor asked for is used if longer.
- Not answering (an outage): 30 seconds, doubling, up to 5 minutes.
- Key refused, or the model is not available to this account: 15 minutes.
  Waiting does not fix these, so the rest is long. Entering the key again,
  or a successful test, ends it at once.

A run that finishes on an AI ends that AI's rest and clears its strikes.

The marks live in Redis, so every worker sees them. If Redis cannot be
reached nothing rests: a missing cooldown only costs the old behaviour,
and a worker that fails because of it would be worse. Tests keep the marks
in this process's memory.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import redis.asyncio as aioredis

from app.agent.providers.base import (
    LLMError,
    ProviderAuthError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.config import get_settings
from app.core.observability import get_logger

log = get_logger(__name__)

RATE_LIMIT_BASE_S = 60
RATE_LIMIT_CAP_S = 900
OUTAGE_BASE_S = 30
OUTAGE_CAP_S = 300
KEY_PROBLEM_S = 900
# Failures this close together count as one run of bad luck, and double the rest.
STRIKE_WINDOW_S = 3600

_REDIS_TIMEOUT_S = 0.5


@dataclass(frozen=True, slots=True)
class Rest:
    """How long an AI rests, and why, in words a person can read."""

    seconds: int
    reason: str


def _rest_key(owner_id: uuid.UUID, provider_key: str) -> str:
    return f"cooldown:rest:{owner_id}:{provider_key}"


def _strike_key(owner_id: uuid.UUID, provider_key: str) -> str:
    return f"cooldown:strikes:{owner_id}:{provider_key}"


def plan(exc: LLMError, strikes: int) -> Rest | None:
    """How long to rest after this failure, or None when resting would not help
    (a request that was too big or malformed says nothing about the AI)."""
    if isinstance(exc, ProviderAuthError):
        return Rest(KEY_PROBLEM_S, "its key was refused")
    if isinstance(exc, ProviderModelNotFoundError):
        return Rest(KEY_PROBLEM_S, "its model is not available to this key")
    if isinstance(exc, ProviderRateLimitError):
        asked = min(max(exc.retry_after or 0.0, 0.0), RATE_LIMIT_CAP_S)
        base = max(RATE_LIMIT_BASE_S, int(asked))
        return Rest(
            min(RATE_LIMIT_CAP_S, base * 2 ** max(strikes - 1, 0)), "reached its usage limit"
        )
    if isinstance(exc, ProviderUnavailableError):
        return Rest(
            min(OUTAGE_CAP_S, OUTAGE_BASE_S * 2 ** max(strikes - 1, 0)), "was not answering"
        )
    return None


# ----------------------------------------------------------------- storage


class _Memory:
    """The same operations, held in this process. Used by tests only."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[str, float]] = {}
        # A function of its own so a test can move time forward.
        self.clock: Callable[[], float] = time.monotonic

    def _alive(self, key: str) -> str | None:
        item = self.values.get(key)
        if item is None:
            return None
        if item[1] <= self.clock():
            del self.values[key]
            return None
        return item[0]

    def get(self, key: str) -> str | None:
        return self._alive(key)

    def set(self, key: str, value: str, seconds: int) -> None:
        self.values[key] = (value, self.clock() + seconds)

    def incr(self, key: str, seconds: int) -> int:
        current = self._alive(key)
        count = int(current or 0) + 1
        expires = self.values[key][1] if current is not None else self.clock() + seconds
        self.values[key] = (str(count), expires)
        return count

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)


_memory = _Memory()


def reset() -> None:
    """Forget every mark held in this process, and the clock. For tests."""
    _memory.values.clear()
    _memory.clock = time.monotonic


def _client() -> aioredis.Redis | None:
    settings = get_settings()
    if settings.environment == "test":
        return None
    client: aioredis.Redis = aioredis.from_url(  # type: ignore[no-untyped-call]
        str(settings.redis_url),
        socket_connect_timeout=_REDIS_TIMEOUT_S,
        socket_timeout=_REDIS_TIMEOUT_S,
    )
    return client


# ------------------------------------------------------------------ public


async def rest(owner_id: uuid.UUID, provider_key: str, exc: LLMError) -> Rest | None:
    """Mark this AI as resting after `exc`. Never raises."""
    if plan(exc, 1) is None:
        return None  # says nothing about the AI, so it earns no strike either
    client = _client()
    try:
        if client is None:
            strikes = _memory.incr(_strike_key(owner_id, provider_key), STRIKE_WINDOW_S)
        else:
            strike_key = _strike_key(owner_id, provider_key)
            strikes = int(await client.incr(strike_key))
            if strikes == 1:
                await client.expire(strike_key, STRIKE_WINDOW_S)
        decided = plan(exc, strikes)
        if decided is None:
            return None
        if client is None:
            _memory.set(_rest_key(owner_id, provider_key), decided.reason, decided.seconds)
        else:
            await client.set(_rest_key(owner_id, provider_key), decided.reason, ex=decided.seconds)
        log.info(
            "model_resting",
            owner_id=str(owner_id),
            provider=provider_key,
            seconds=decided.seconds,
            reason=decided.reason,
        )
        return decided
    except Exception:  # noqa: BLE001 - a missing cooldown must never fail a run
        log.warning("cooldown_unavailable", provider=provider_key)
        return None
    finally:
        if client is not None:
            await client.aclose()


async def resting(owner_id: uuid.UUID, provider_keys: Iterable[str]) -> dict[str, str]:
    """Which of these AIs are resting right now, and why. Never raises."""
    keys = list(dict.fromkeys(provider_keys))
    if not keys:
        return {}
    client = _client()
    try:
        if client is None:
            values = [_memory.get(_rest_key(owner_id, k)) for k in keys]
        else:
            raw = await client.mget([_rest_key(owner_id, k) for k in keys])
            values = [v.decode() if isinstance(v, bytes) else v for v in raw]
        return {k: v for k, v in zip(keys, values, strict=True) if v}
    except Exception:  # noqa: BLE001 - see rest()
        log.warning("cooldown_unavailable")
        return {}
    finally:
        if client is not None:
            await client.aclose()


async def recovered(owner_id: uuid.UUID, provider_key: str) -> None:
    """This AI works again: end its rest and forget its strikes. Never raises."""
    client = _client()
    try:
        keys = (_rest_key(owner_id, provider_key), _strike_key(owner_id, provider_key))
        if client is None:
            _memory.delete(*keys)
        else:
            await client.delete(*keys)
    except Exception:  # noqa: BLE001 - see rest()
        log.warning("cooldown_unavailable", provider=provider_key)
    finally:
        if client is not None:
            await client.aclose()
