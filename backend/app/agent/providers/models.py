"""Which of a key's models are worth offering, and in what order to try them.

A provider's model list is raw: it mixes chat models with embedding,
speech, image and moderation ones, plus previews and retired names. And
what a key can *use* depends on the plan (a free key often cannot reach
a paid model), which no list says. So the platform filters the list to
chat models, orders it by what is most likely to work, and lets a tiny
real call settle which one does.
"""

from __future__ import annotations

import re

# Not for chatting, whatever the provider calls them.
_NOT_CHAT = re.compile(
    r"embed|whisper|tts|speech|audio|transcri|moderation|guard|safety|rerank|"
    r"dall-e|imagen|image|veo|sora|realtime|live|aqa|vision-only|"
    r"(^|[-_/])(ocr|asr)([-_/]|$)",
    re.IGNORECASE,
)

# Likely to need a special plan, or to change under you.
_RISKY = re.compile(r"preview|experimental|[-_]exp([-_]|$)|beta|thinking|deprecated", re.IGNORECASE)

# Broadly capable models that most keys, free ones included, can reach.
# Earlier is tried first. A match is by substring, so new point releases
# of the same family are still found.
_PREFERRED = (
    "llama-3.3-70b",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "claude-sonnet",
    "claude-haiku",
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "mistral-small",
    "deepseek-chat",
    "qwen",
    "llama-3.1-8b",
    "llama",
    "gemini",
    "gpt",
    "claude",
    "mistral",
)


def is_chat_model(model_id: str) -> bool:
    return bool(model_id) and not _NOT_CHAT.search(model_id)


def chat_models(ids: list[str]) -> list[str]:
    """Only the models that can hold a conversation, without duplicates."""
    return list(dict.fromkeys(m for m in ids if is_chat_model(m)))


def try_order(ids: list[str], current: str | None = None) -> list[str]:
    """The same models, most likely to work first.

    The one already in use stays first when it is still listed. Then the
    well-known general models, stable ones before previews, then the
    rest as the provider listed them.
    """

    def score(model: str) -> tuple[int, int, int]:
        lowered = model.lower()
        family = next((i for i, p in enumerate(_PREFERRED) if p in lowered), len(_PREFERRED))
        return (0 if model == current else 1, int(bool(_RISKY.search(model))), family)

    return sorted(chat_models(ids), key=score)
