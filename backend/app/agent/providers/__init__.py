"""LLM providers.

Three adapters cover everything we support: Gemini and Claude speak
their own formats, and one OpenAI-compatible adapter covers OpenAI,
Groq, DeepSeek, OpenRouter, Mistral and any self-hosted open-source
model server.
"""

from app.agent.providers.anthropic import AnthropicProvider
from app.agent.providers.base import (
    LLMError,
    LLMProvider,
    LLMReply,
    Message,
    Role,
    StopReason,
    ToolCall,
    ToolSchema,
    Usage,
)
from app.agent.providers.gemini import GeminiProvider
from app.agent.providers.openai_compatible import BASE_URLS, OpenAICompatibleProvider

# The one provider whose address the company gives us.
CUSTOM_PROVIDER = "custom"


def build_provider(provider_key: str, api_key: str, *, base_url: str | None = None) -> LLMProvider:
    """Pick the adapter for a provider key."""
    if provider_key == "gemini":
        return GeminiProvider(api_key)
    if provider_key == "anthropic":
        return AnthropicProvider(api_key)
    return OpenAICompatibleProvider(api_key, provider_key=provider_key, base_url=base_url)


__all__ = [
    "BASE_URLS",
    "CUSTOM_PROVIDER",
    "AnthropicProvider",
    "GeminiProvider",
    "LLMError",
    "LLMProvider",
    "LLMReply",
    "Message",
    "OpenAICompatibleProvider",
    "Role",
    "StopReason",
    "ToolCall",
    "ToolSchema",
    "Usage",
    "build_provider",
]
