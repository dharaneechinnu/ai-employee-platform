"""Several of a person's AIs behind one provider, in order of preference.

The agent loop talks to one provider. With automatic routing, that
provider is this: it sends each call to the current choice and, when
that AI is rate-limited, down, or refuses the key, moves to the next
connected AI and tries the same call again. The run carries on instead
of failing because one vendor had a bad minute.

What happens depends on what went wrong:

- Rate limit: the AI is fine, just busy. Wait (as long as it asked, else
  a growing pause) and try it again, twice, before giving up on it.
- Unavailable (a vendor outage or timeout): one quick retry, since these
  are often a blip, then the next AI.
- Key refused, or the model is not available to this account: waiting
  cannot help, so the next AI at once.
- A request the AI rejected as malformed is not retried anywhere: the
  next AI would most likely reject it too, and the error is more useful
  to the person than three identical failures.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agent.providers.base import (
    LLMError,
    LLMProvider,
    LLMReply,
    Message,
    ProviderAuthError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    ToolSchema,
)

# Pauses before each retry on the same AI, by kind of failure (seconds).
RATE_LIMIT_PAUSES = (2.0, 5.0)
UNAVAILABLE_PAUSES = (1.0,)
MAX_PAUSE_S = 20.0


@dataclass(slots=True)
class Option:
    provider: LLMProvider
    provider_key: str
    model: str


OnSwitch = Callable[[Option, Option, LLMError], Awaitable[None]]
# (option, error, attempt number, seconds about to be waited)
OnRetry = Callable[[Option, LLMError, int, float], Awaitable[None]]


async def pause(seconds: float) -> None:
    """The wait before a retry. A function of its own so tests can skip it."""
    await asyncio.sleep(seconds)


def pauses_for(exc: LLMError) -> tuple[float, ...]:
    """How long to wait before each retry of the same AI. Empty: do not retry."""
    if isinstance(exc, ProviderRateLimitError):
        if exc.retry_after is not None:
            return (min(max(exc.retry_after, 0.0), MAX_PAUSE_S),) * len(RATE_LIMIT_PAUSES)
        return RATE_LIMIT_PAUSES
    if isinstance(exc, ProviderUnavailableError):
        return UNAVAILABLE_PAUSES
    return ()


class FallbackProvider(LLMProvider):
    def __init__(
        self,
        options: list[Option],
        *,
        on_switch: OnSwitch | None = None,
        on_retry: OnRetry | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not options:
            raise ValueError("FallbackProvider needs at least one option")
        super().__init__(api_key="")
        self.options = options
        self.index = 0
        self.on_switch = on_switch
        self.on_retry = on_retry
        self._sleep = sleep

    @property
    def current(self) -> Option:
        return self.options[self.index]

    @property
    def provider_key(self) -> str:  # type: ignore[override]
        return self.current.provider_key

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMReply:
        retries = 0  # on the current option
        while True:
            option = self.current
            try:
                return await option.provider.complete(
                    messages=messages,
                    model=option.model,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except LLMError as exc:
                pauses = pauses_for(exc)
                if retries < len(pauses):
                    delay = pauses[retries]
                    retries += 1
                    if self.on_retry:
                        await self.on_retry(option, exc, retries, delay)
                    await (self._sleep or pause)(delay)
                    continue
                worth_switching = exc.retryable or isinstance(
                    exc, ProviderAuthError | ProviderModelNotFoundError
                )
                if not worth_switching or self.index + 1 >= len(self.options):
                    raise
                self.index += 1
                retries = 0
                if self.on_switch:
                    await self.on_switch(option, self.current, exc)

    async def check(self, model: str) -> None:
        await self.current.provider.check(self.current.model)

    async def list_models(self) -> list[str]:
        return await self.current.provider.list_models()
