"""Attempt limits for the public sign-in and sign-up routes.

Counts live in Redis, so every API worker (and a restart) sees the same
numbers. If Redis cannot be reached the limiter falls back to this
process's memory instead of failing the request: a limit that is only
per-worker is still better than a sign-in page that is down. Tests run
in memory only.

A fixed window: the first attempt starts a clock of `window_seconds`,
and the count resets when it runs out.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

import redis.asyncio as aioredis

from app.config import get_settings
from app.core.errors import RateLimitError
from app.core.observability import get_logger

log = get_logger(__name__)

_REDIS_TIMEOUT_S = 0.5


class RateLimiter:
    def __init__(self, *, name: str, limit: int, window_seconds: int, message: str) -> None:
        self.name = name
        self.limit = limit
        self.window = window_seconds
        self.message = message
        self._memory: dict[str, deque[float]] = defaultdict(deque)

    # ------------------------------------------------------------ public

    async def check(self, key: str) -> None:
        """Raise when `key` is already at the limit. Counts nothing."""
        if await self._count(key) >= self.limit:
            raise RateLimitError(self.message)

    async def hit(self, key: str) -> None:
        """Record one attempt for `key`."""
        await self._add(key)

    async def consume(self, key: str) -> None:
        """Record one attempt and raise if that put `key` over the limit."""
        if await self._add(key) > self.limit:
            raise RateLimitError(self.message)

    async def clear(self, key: str) -> None:
        """Forget `key`, for example after a successful sign-in."""
        self._memory.pop(key, None)
        client = self._client()
        if client is None:
            return
        try:
            await client.delete(self._redis_key(key))
        except Exception:  # noqa: BLE001 - see _client()
            log.warning("rate_limit_redis_unavailable", limiter=self.name)
        finally:
            await client.aclose()

    def reset(self) -> None:
        """Forget everything held in this process. For tests."""
        self._memory.clear()

    # ----------------------------------------------------------- storage

    def _redis_key(self, key: str) -> str:
        return f"ratelimit:{self.name}:{key}"

    @staticmethod
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

    async def _count(self, key: str) -> int:
        client = self._client()
        if client is not None:
            try:
                value = await client.get(self._redis_key(key))
                return int(value or 0)
            except Exception:  # noqa: BLE001 - Redis down is not a reason to refuse a sign-in
                log.warning("rate_limit_redis_unavailable", limiter=self.name)
            finally:
                await client.aclose()
        return len(self._fresh(key))

    async def _add(self, key: str) -> int:
        client = self._client()
        if client is not None:
            try:
                redis_key = self._redis_key(key)
                count = int(await client.incr(redis_key))
                if count == 1:
                    await client.expire(redis_key, self.window)
                return count
            except Exception:  # noqa: BLE001
                log.warning("rate_limit_redis_unavailable", limiter=self.name)
            finally:
                await client.aclose()
        hits = self._fresh(key)
        hits.append(time.monotonic())
        return len(hits)

    def _fresh(self, key: str) -> deque[float]:
        now = time.monotonic()
        hits = self._memory[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        return hits


register_limiter = RateLimiter(
    name="register",
    limit=10,
    window_seconds=3600,
    message="Too many sign-ups from here. Please try again in an hour.",
)

# Counts wrong passwords only, per address and account name, so one person
# mistyping does not lock anyone else out and a guessing run is slowed to a crawl.
login_limiter = RateLimiter(
    name="login",
    limit=8,
    window_seconds=900,
    message="Too many sign-in attempts. Please wait 15 minutes and try again.",
)
