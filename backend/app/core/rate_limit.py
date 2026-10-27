"""A small per-client limiter for the public sign-up route.

In-process only: the counts live in this worker's memory, so they reset
on restart and are not shared between workers. That is enough to blunt
casual abuse on a single-instance personal deployment; put a shared
store behind it before running several workers.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.core.errors import RateLimitError


class SlidingWindowLimiter:
    def __init__(self, *, limit: int, window_seconds: float, message: str) -> None:
        self.limit = limit
        self.window = window_seconds
        self.message = message
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Count one attempt for `key`, or raise when it is over the limit."""
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            raise RateLimitError(self.message)
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()


register_limiter = SlidingWindowLimiter(
    limit=10,
    window_seconds=3600,
    message="Too many sign-ups from here. Please try again in an hour.",
)
