"""Google Gemini, via the REST API.

Gemini's wire format differs from OpenAI's in four ways that this
adapter hides:

- the system prompt is a top-level `systemInstruction`, not a message
- messages are `contents` with `parts`, and the assistant role is
  called "model"
- tool calls arrive as `functionCall` parts, results go back as
  `functionResponse` parts
- `finishReason` uses its own vocabulary

Deliberately not using the OpenAI-compatibility endpoint: compatibility
layers lag on exactly the features this product leans on, namely
fine-grained tool calling.
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
    parse_retry_after,
)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

_STOP_REASONS = {
    "STOP": StopReason.END_TURN,
    "MAX_TOKENS": StopReason.MAX_TOKENS,
    "SAFETY": StopReason.ERROR,
    "RECITATION": StopReason.ERROR,
}


class GeminiProvider(LLMProvider):
    provider_key = "gemini"

    def _to_contents(self, messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
        system: str | None = None
        contents: list[dict[str, Any]] = []

        for m in messages:
            if m.role is Role.SYSTEM:
                # Gemini takes this separately, not as a turn.
                system = m.content
                continue

            if m.role is Role.TOOL:
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": m.name or "tool",
                                    "response": {"result": m.content or ""},
                                }
                            }
                        ],
                    }
                )
                continue

            if m.role is Role.ASSISTANT and m.raw and m.raw_from in (None, "gemini"):
                # As Gemini sent them: newer models attach a thought
                # signature to tool calls and reject a turn without it.
                contents.append({"role": "model", "parts": m.raw})
                continue

            parts: list[dict[str, Any]] = []
            if m.content:
                parts.append({"text": m.content})
            for call in m.tool_calls:
                parts.append({"functionCall": {"name": call.name, "args": call.arguments}})

            if parts:
                contents.append(
                    {"role": "model" if m.role is Role.ASSISTANT else "user", "parts": parts}
                )

        return system, contents

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMReply:
        system, contents = self._to_contents(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {"name": t.name, "description": t.description, "parameters": t.parameters}
                        for t in tools
                    ]
                }
            ]

        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.post(
                    f"{BASE_URL}/models/{model}:generateContent",
                    params={"key": self.api_key},
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                raise ProviderUnavailableError(f"Gemini timed out after {self.timeout_s}s") from exc
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(f"Could not reach Gemini: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        self._raise_for_status(response)

        return self._parse(response.json(), model=model, latency_ms=latency_ms)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return

        detail = response.text[:300]
        if response.status_code in (401, 403):
            raise ProviderAuthError(
                f"Gemini rejected the API key: {detail}", status_code=response.status_code
            )
        if response.status_code == 429:
            raise ProviderRateLimitError(
                f"Gemini rate limit reached: {detail}",
                status_code=429,
                retry_after=parse_retry_after(response.headers),
            )
        if response.status_code >= 500:
            raise ProviderUnavailableError(
                f"Gemini error: {detail}", status_code=response.status_code
            )
        raise ProviderRequestError(
            f"Gemini rejected the request: {detail}", status_code=response.status_code
        )

    @staticmethod
    def _parse(data: dict[str, Any], *, model: str, latency_ms: int) -> LLMReply:
        candidates = data.get("candidates") or []
        if not candidates:
            # A prompt blocked by a safety filter returns no candidate at
            # all, so this is an expected shape, not a parsing failure.
            raise ProviderRequestError(
                "Gemini returned no candidates (the prompt may have been blocked)"
            )

        candidate = candidates[0]
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for part in candidate.get("content", {}).get("parts", []):
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(
                    ToolCall(id=ToolCall.new_id(), name=fc["name"], arguments=fc.get("args") or {})
                )

        usage_meta = data.get("usageMetadata", {})
        stop = (
            StopReason.TOOL_USE
            if tool_calls
            else _STOP_REASONS.get(candidate.get("finishReason", ""), StopReason.END_TURN)
        )

        return LLMReply(
            message=Message(
                role=Role.ASSISTANT,
                content="".join(text_parts) or None,
                tool_calls=tool_calls,
                raw=candidate.get("content", {}).get("parts") or None,
                raw_from="gemini",
            ),
            stop_reason=stop,
            usage=Usage(
                prompt_tokens=usage_meta.get("promptTokenCount", 0),
                output_tokens=usage_meta.get("candidatesTokenCount", 0),
            ),
            model=model,
            latency_ms=latency_ms,
        )

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.get(
                    f"{BASE_URL}/models", params={"key": self.api_key, "pageSize": 200}
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(f"Could not reach Gemini: {exc}") from exc
        self._raise_for_status(response)
        return [
            m["name"].removeprefix("models/")
            for m in response.json().get("models", [])
            if "generateContent" in (m.get("supportedGenerationMethods") or [])
        ]

    async def check(self, model: str) -> None:
        await self.complete(
            messages=[Message(role=Role.USER, content="ping")], model=model, max_tokens=8
        )
