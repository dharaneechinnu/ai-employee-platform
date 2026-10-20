"""Several of a person's AIs behind one provider, in order of preference.

The agent loop talks to one provider. With automatic routing, that
provider is this: it sends each call to the current choice and, when
that AI is rate-limited, down, or refuses the key, moves to the next
connected AI and tries the same call again. The run carries on instead
of failing because one vendor had a bad minute.

A request the AI rejected as malformed is not retried elsewhere: the
next AI would most likely reject it too, and the error is more useful
to the person than three identical failures.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agent.providers.base import (
    LLMError,
    LLMProvider,
    LLMReply,
    Message,
    ProviderAuthError,
    ToolSchema,
)


@dataclass(slots=True)
class Option:
    provider: LLMProvider
    provider_key: str
    model: str


OnSwitch = Callable[[Option, Option, LLMError], Awaitable[None]]


class FallbackProvider(LLMProvider):
    def __init__(self, options: list[Option], *, on_switch: OnSwitch | None = None) -> None:
        if not options:
            raise ValueError("FallbackProvider needs at least one option")
        super().__init__(api_key="")
        self.options = options
        self.index = 0
        self.on_switch = on_switch

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
                worth_switching = exc.retryable or isinstance(exc, ProviderAuthError)
                if not worth_switching or self.index + 1 >= len(self.options):
                    raise
                self.index += 1
                if self.on_switch:
                    await self.on_switch(option, self.current, exc)

    async def check(self, model: str) -> None:
        await self.current.provider.check(self.current.model)

    async def list_models(self) -> list[str]:
        return await self.current.provider.list_models()
