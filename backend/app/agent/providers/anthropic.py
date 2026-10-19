"""Anthropic Claude, via the Messages API.

Claude's wire format differs from OpenAI's in ways this adapter hides:

- the system prompt is a top-level `system` field, not a message
- a turn's content is a list of blocks: `text`, `tool_use`, `thinking`
- tool results go back as `tool_result` blocks inside one user message,
  all results for a turn together
- the key goes in `x-api-key`, with an `anthropic-version` header

Two rules matter for agents. Thinking blocks must be sent back exactly
as they arrived, so the assistant turn keeps its raw blocks. And
current models reject sampling settings like `temperature`, so none
are sent; the model's own defaults apply.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderUnavailableError,
    Role,
    StopReason,
    ToolCall,
    ToolSchema,
    Usage,
)

BASE_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"

# Thinking shares the output budget, so a reply needs more room than a
# model without it. Large enough not to cut a turn short, small enough
# to stay under the HTTP timeout without streaming.
MIN_MAX_TOKENS = 16_000

_STOP_REASONS = {
    "end_turn": StopReason.END_TURN,
    "stop_sequence": StopReason.END_TURN,
    "pause_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "refusal": StopReason.ERROR,
}


class AnthropicProvider(LLMProvider):
    provider_key = "anthropic"

    def __init__(self, api_key: str, *, timeout_s: float = 120.0) -> None:
        super().__init__(api_key, timeout_s=timeout_s)

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "anthropic-version": API_VERSION}

    @staticmethod
    def _to_payload(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
        system: str | None = None
        out: list[dict[str, Any]] = []

        for m in messages:
            if m.role is Role.SYSTEM:
                system = m.content
                continue

            if m.role is Role.TOOL:
                block: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": m.content or "",
                }
                if m.content and m.content.startswith("Tool failed ("):
                    block["is_error"] = True
                # Every result for one turn goes in a single user message.
                previous = out[-1] if out else None
                if (
                    previous
                    and previous["role"] == "user"
                    and isinstance(previous["content"], list)
                    and all(b.get("type") == "tool_result" for b in previous["content"])
                ):
                    previous["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
                continue

            if m.role is Role.ASSISTANT:
                if m.raw:
                    # Exactly as Claude sent it, thinking blocks included.
                    out.append({"role": "assistant", "content": m.raw})
                    continue
                blocks: list[dict[str, Any]] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for call in m.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": call.arguments,
                        }
                    )
                if blocks:
                    out.append({"role": "assistant", "content": blocks})
                continue

            out.append({"role": "user", "content": m.content or ""})

        return system, out

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMReply:
        system, payload_messages = self._to_payload(messages)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max(max_tokens, MIN_MAX_TOKENS),
            "messages": payload_messages,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]

        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.post(
                    f"{BASE_URL}/messages", headers=self._headers(), json=payload
                )
            except httpx.TimeoutException as exc:
                raise ProviderUnavailableError(f"Claude timed out after {self.timeout_s}s") from exc
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(f"Could not reach Claude: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        _raise_for_status(response)
        return self._parse(response.json(), model=model, latency_ms=latency_ms)

    @staticmethod
    def _parse(data: dict[str, Any], *, model: str, latency_ms: int) -> LLMReply:
        blocks: list[dict[str, Any]] = data.get("content") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id") or ToolCall.new_id(),
                        name=block.get("name", ""),
                        arguments=block.get("input") or {},
                    )
                )

        stop = (
            StopReason.TOOL_USE
            if tool_calls
            else _STOP_REASONS.get(data.get("stop_reason") or "", StopReason.END_TURN)
        )
        text = "".join(text_parts) or None
        if data.get("stop_reason") == "refusal" and not text:
            text = "Claude declined this request."

        usage = data.get("usage") or {}
        return LLMReply(
            message=Message(role=Role.ASSISTANT, content=text, tool_calls=tool_calls, raw=blocks),
            stop_reason=stop,
            usage=Usage(
                prompt_tokens=usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            ),
            model=data.get("model") or model,
            latency_ms=latency_ms,
        )

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.get(
                    f"{BASE_URL}/models", headers=self._headers(), params={"limit": 100}
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(f"Could not reach Claude: {exc}") from exc
        _raise_for_status(response)
        return [m["id"] for m in response.json().get("data", []) if m.get("id")]

    async def check(self, model: str) -> None:
        """Looks the model up rather than generating text: it proves the
        key and the model name are both right, and costs nothing."""
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.get(f"{BASE_URL}/models/{model}", headers=self._headers())
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(f"Could not reach Claude: {exc}") from exc
        if response.status_code == 404:
            raise ProviderRequestError(f"Claude has no model called '{model}'.", status_code=404)
        _raise_for_status(response)


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    detail = response.text[:300]
    code = response.status_code
    if code in (401, 403):
        raise ProviderAuthError(f"Claude rejected the API key: {detail}", status_code=code)
    if code == 429:
        raise ProviderRateLimitError(f"Claude rate limit reached: {detail}", status_code=429)
    if code >= 500:  # includes 529, "overloaded"
        raise ProviderUnavailableError(f"Claude error: {detail}", status_code=code)
    raise ProviderRequestError(f"Claude rejected the request: {detail}", status_code=code)
