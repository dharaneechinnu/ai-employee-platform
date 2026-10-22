"""One adapter for every provider that speaks the OpenAI chat format.

Covers Groq, NVIDIA NIM, DeepSeek, OpenRouter, Together, Mistral and
OpenAI itself, plus any server a company runs (vLLM, Ollama, LM
Studio, LiteLLM). They differ only in base URL, so a single adapter
is less code and fewer places for a bug to hide than one per vendor.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.agent.providers.base import (
    LLMProvider,
    LLMReply,
    Message,
    ProviderAuthError,
    ProviderModelNotFoundError,
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

# Base URLs per provider key. Adding a vendor that speaks this format is
# one line here, not a new adapter.
BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "mistral": "https://api.mistral.ai/v1",
}

_STOP_REASONS = {
    "stop": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.ERROR,
}


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        *,
        provider_key: str = "openai",
        base_url: str | None = None,
        auth_header: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        super().__init__(api_key, timeout_s=timeout_s)
        self.provider_key = provider_key
        # Some providers want the key under their own header as well as
        # `Authorization: Bearer`. It comes from the provider's catalog
        # row, so a new one needs no code.
        self.auth_header = auth_header
        self.base_url = base_url or BASE_URLS.get(provider_key, BASE_URLS["openai"])

    @staticmethod
    def _to_payload_messages(messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role is Role.TOOL:
                out.append(
                    {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""}
                )
                continue

            entry: dict[str, Any] = {"role": m.role.value, "content": m.content or ""}
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in m.tool_calls
                ]
            out.append(entry)
        return out

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMReply:
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._to_payload_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                raise ProviderUnavailableError(
                    f"{self.provider_key} timed out after {self.timeout_s}s"
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(
                    f"Could not reach {self.provider_key}: {exc}"
                ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        self._raise_for_status(response)
        return self._parse(response.json(), model=model, latency_ms=latency_ms)

    def _headers(self) -> dict[str, str]:
        # A self-hosted server often has no key at all.
        if not self.api_key:
            return {}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.auth_header:
            headers[self.auth_header] = self.api_key
        return headers

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(
                    f"Could not reach {self.provider_key}: {exc}"
                ) from exc
        self._raise_for_status(response)
        return sorted(m["id"] for m in response.json().get("data", []) if m.get("id"))

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return

        detail = response.text[:300]
        code = response.status_code
        if code in (401, 403):
            raise ProviderAuthError(
                f"{self.provider_key} rejected the API key: {detail}", status_code=code
            )
        if code == 429:
            raise ProviderRateLimitError(
                f"{self.provider_key} rate limit reached: {detail}",
                status_code=429,
                retry_after=parse_retry_after(response.headers),
            )
        if code >= 500:
            raise ProviderUnavailableError(f"{self.provider_key} error: {detail}", status_code=code)
        if code == 404 or "model_not_found" in detail:
            # Worth separating from every other 4xx. "model_not_found"
            # usually means the key is fine and the account simply
            # cannot reach that model — a free tier asking for a paid
            # one. Reported as a bad request it reads like a bad key,
            # and people go and regenerate a key that was never wrong.
            raise ProviderModelNotFoundError(
                f"{self.provider_key} does not serve that model to this account. "
                "The key itself may be fine — some models need a paid plan. "
                f"Provider said: {detail}",
                status_code=code,
            )
        raise ProviderRequestError(
            f"{self.provider_key} rejected the request: {detail}", status_code=code
        )

    @staticmethod
    def _parse(data: dict[str, Any], *, model: str, latency_ms: int) -> LLMReply:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderRequestError("Provider returned no choices")

        message = choices[0].get("message", {})
        tool_calls: list[ToolCall] = []

        for raw in message.get("tool_calls") or []:
            fn = raw.get("function", {})
            try:
                arguments = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                # Models do occasionally emit malformed JSON here. An
                # empty dict lets the tool reject it with a clear message
                # the model can recover from, which beats crashing the run.
                arguments = {}
            tool_calls.append(
                ToolCall(
                    id=raw.get("id") or ToolCall.new_id(),
                    name=fn.get("name", ""),
                    arguments=arguments,
                )
            )

        usage = data.get("usage") or {}
        stop = (
            StopReason.TOOL_USE
            if tool_calls
            else _STOP_REASONS.get(choices[0].get("finish_reason", ""), StopReason.END_TURN)
        )

        return LLMReply(
            message=Message(
                role=Role.ASSISTANT, content=message.get("content"), tool_calls=tool_calls
            ),
            stop_reason=stop,
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            ),
            model=model,
            latency_ms=latency_ms,
        )

    async def check(self, model: str) -> None:
        await self.complete(
            messages=[Message(role=Role.USER, content="ping")], model=model, max_tokens=8
        )
