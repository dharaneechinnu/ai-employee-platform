"""The Claude adapter: the format differences it hides."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

import app.agent.providers.anthropic as anthropic_module
from app.agent.providers import build_provider
from app.agent.providers.anthropic import AnthropicProvider
from app.agent.providers.base import (
    Message,
    ProviderAuthError,
    Role,
    StopReason,
    ToolCall,
    ToolSchema,
)

REAL_CLIENT = httpx.AsyncClient
THINKING = {"type": "thinking", "thinking": "", "signature": "sig-abc"}


def _client_with(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        anthropic_module.httpx,
        "AsyncClient",
        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(record), **kw),
    )
    return seen


def test_build_provider_picks_the_claude_adapter() -> None:
    assert isinstance(build_provider("anthropic", "sk-ant-x"), AnthropicProvider)


async def test_a_tool_call_round_trip_keeps_thinking_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = {
        "model": "claude-opus-5-5",
        "content": [
            THINKING,
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "toolu_1", "name": "recall", "input": {"query": "refunds"}},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 120, "output_tokens": 30, "cache_read_input_tokens": 10},
    }
    seen = _client_with(monkeypatch, lambda r: httpx.Response(200, json=reply))
    provider = AnthropicProvider("sk-ant-test")

    first = await provider.complete(
        messages=[
            Message(role=Role.SYSTEM, content="You are Ravi."),
            Message(role=Role.USER, content="What is our refund rule?"),
        ],
        model="claude-opus-5-5",
        tools=[ToolSchema("recall", "Look up memory", {"type": "object", "properties": {}})],
    )

    request = seen[0]
    body = json.loads(request.content)
    assert request.headers["x-api-key"] == "sk-ant-test"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert body["system"] == "You are Ravi."
    assert body["messages"] == [{"role": "user", "content": "What is our refund rule?"}]
    assert body["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    assert "temperature" not in body  # current Claude models reject it
    assert body["max_tokens"] >= 16000  # room for thinking

    assert first.stop_reason is StopReason.TOOL_USE
    assert first.tool_calls[0].arguments == {"query": "refunds"}
    assert first.usage.prompt_tokens == 130

    # Next turn: the assistant turn goes back exactly as received, and
    # parallel results share one user message.
    second_turn = [
        Message(role=Role.USER, content="What is our refund rule?"),
        first.message,
        Message(role=Role.TOOL, content="30 days", tool_call_id="toolu_1", name="recall"),
        Message(
            role=Role.TOOL, content="Tool failed (x): no", tool_call_id="toolu_2", name="recall"
        ),
    ]
    payload = AnthropicProvider._to_payload(second_turn)[1]
    assert payload[1] == {"role": "assistant", "content": reply["content"]}
    assert payload[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "30 days"},
        {
            "type": "tool_result",
            "tool_use_id": "toolu_2",
            "content": "Tool failed (x): no",
            "is_error": True,
        },
    ]


def test_a_turn_without_raw_blocks_is_rebuilt() -> None:
    """Turns saved before this adapter existed have no raw blocks."""
    payload = AnthropicProvider._to_payload(
        [
            Message(
                role=Role.ASSISTANT, content="Hi", tool_calls=[ToolCall("t1", "recall", {"q": 1})]
            )
        ]
    )[1]
    assert payload == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Hi"},
                {"type": "tool_use", "id": "t1", "name": "recall", "input": {"q": 1}},
            ],
        }
    ]


async def test_a_bad_key_and_a_wrong_model_are_told_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    _client_with(monkeypatch, lambda r: httpx.Response(401, json={"error": {}}))
    with pytest.raises(ProviderAuthError):
        await AnthropicProvider("bad").check("claude-opus-5-5")

    _client_with(monkeypatch, lambda r: httpx.Response(404, json={"error": {}}))
    with pytest.raises(Exception, match="no model called"):
        await AnthropicProvider("good").check("claude-made-up")


async def test_lists_models(monkeypatch: pytest.MonkeyPatch) -> None:
    _client_with(
        monkeypatch,
        lambda r: httpx.Response(
            200, json={"data": [{"id": "claude-opus-5-5"}, {"id": "claude-haiku-5-5"}]}
        ),
    )
    assert await AnthropicProvider("k").list_models() == ["claude-opus-5-5", "claude-haiku-5-5"]
