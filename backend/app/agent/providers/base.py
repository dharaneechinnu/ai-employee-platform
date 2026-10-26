"""The LLM provider interface.

Everything above this layer is provider-agnostic. The interface exists
to normalise the four things that genuinely differ between vendors:

- the shape of a tool call
- where the system prompt goes
- streaming event types
- stop reasons

Implemented with plain httpx rather than vendor SDKs. Three reasons:
fewer dependencies, one consistent error surface, and recorded
request/response pairs that are trivial to replay in tests.
"""

from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class StopReason(StrEnum):
    """Normalised across providers."""

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    ERROR = "error"


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]


@dataclass(slots=True)
class Message:
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # set on TOOL messages
    name: str | None = None  # the tool's name, on TOOL messages
    # The provider's own content blocks for an assistant turn, kept so
    # they can be sent back unchanged. Claude needs this: its thinking
    # blocks must be returned exactly as received or the next turn fails.
    raw: list[dict[str, Any]] | None = None
    # Which provider wrote `raw`. Only that provider can read it back:
    # when a run moves to another AI, the plain fields are used instead.
    raw_from: str | None = None


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.output_tokens


@dataclass(slots=True)
class LLMReply:
    message: Message
    stop_reason: StopReason
    usage: Usage
    model: str
    latency_ms: int = 0

    @property
    def text(self) -> str | None:
        return self.message.content

    @property
    def tool_calls(self) -> list[ToolCall]:
        return self.message.tool_calls


@dataclass(slots=True)
class ToolSchema:
    """A tool as the model sees it."""

    name: str
    description: str
    parameters: dict[str, Any]


class LLMError(Exception):
    """Base for provider failures.

    `retryable` is the field the worker acts on. Retrying a bad API key
    is pointless; not retrying a rate limit wastes a usable request.
    """

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        # Seconds the vendor asked us to wait (a rate limit's Retry-After).
        self.retry_after = retry_after


def parse_retry_after(headers: Any) -> float | None:
    """Seconds from a Retry-After header, when it is the plain-number form."""
    try:
        return max(float(headers.get("retry-after")), 0.0)
    except (TypeError, ValueError, AttributeError):
        return None


class ProviderRateLimitError(LLMError):
    retryable = True


class ProviderUnavailableError(LLMError):
    retryable = True


class ProviderAuthError(LLMError):
    retryable = False


class ProviderRequestError(LLMError):
    retryable = False


class ProviderModelNotFoundError(LLMError):
    """The model name is wrong, or this account cannot reach it.

    Not retryable, and distinct from an auth error: the key may be
    perfectly good. Conflating the two sends people off to regenerate
    a key that was never the problem.
    """

    retryable = False


class LLMProvider(ABC):
    """One vendor. Constructed with the company's own API key."""

    provider_key: str

    def __init__(self, api_key: str, *, timeout_s: float = 60.0) -> None:
        self.api_key = api_key
        self.timeout_s = timeout_s

    @abstractmethod
    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMReply: ...

    async def list_models(self) -> list[str]:
        """Model ids this key can use, for the model picker.

        Optional: an adapter that cannot list returns nothing, and the
        company types a model name instead.
        """
        return []

    @abstractmethod
    async def check(self, model: str) -> None:
        """One cheap call, to verify the key works.

        Raises an LLMError subclass on failure so the caller can tell a
        bad key from an outage rather than reporting both as "failed".
        """


class ProviderTooLargeError(LLMError):
    """The request is bigger than this AI will take, whatever the wait.

    Not a rate limit: a request over a per-minute token cap, or over the
    model's context, fails again however long we pause. So it is never
    retried on the same AI. Another AI with a bigger limit may take it,
    and the loop can send a slimmer request (see `app.agent.slim`).
    """

    retryable = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        limit_tokens: int | None = None,
        requested_tokens: int | None = None,
    ):
        super().__init__(message, status_code=status_code)
        self.limit_tokens = limit_tokens
        self.requested_tokens = requested_tokens


# What vendors say when the request itself is too big. Groq answers 413
# ("Request too large ... tokens per minute"), Claude answers 413
# "request_too_large", and others answer 400 about the context window.
_TOO_LARGE = re.compile(
    r"request too large|request_too_large|payload too large|context[ _]length|"
    r"maximum context|exceeds? the maximum number of tokens|too many tokens",
    re.IGNORECASE,
)
_LIMIT_AND_REQUESTED = re.compile(r"Limit (\d+), Requested (\d+)")


def too_large_error(provider: str, status_code: int, detail: str) -> ProviderTooLargeError | None:
    """A `ProviderTooLargeError` if this failed response means "too big"."""
    if status_code != 413 and not _TOO_LARGE.search(detail):
        return None
    numbers = _LIMIT_AND_REQUESTED.search(detail)
    limit, requested = (int(numbers[1]), int(numbers[2])) if numbers else (None, None)
    size = f" ({requested} tokens against a limit of {limit})" if numbers else ""
    return ProviderTooLargeError(
        f"{provider} cannot take a request this large{size}. Provider said: {detail}",
        status_code=status_code,
        limit_tokens=limit,
        requested_tokens=requested,
    )
