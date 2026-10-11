"""LLM providers.

Two adapters cover everything we support: Gemini speaks its own
format, and one OpenAI-compatible adapter covers Groq, NVIDIA,
DeepSeek, OpenRouter, Together and Ollama.
"""

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


def build_provider(provider_key: str, api_key: str) -> LLMProvider:
    """Pick the adapter for a provider key."""
    if provider_key == "gemini":
        return GeminiProvider(api_key)
    return OpenAICompatibleProvider(api_key, provider_key=provider_key)


__all__ = [
    "BASE_URLS",
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
