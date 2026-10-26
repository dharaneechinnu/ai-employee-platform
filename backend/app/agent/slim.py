"""A slimmer request, for an AI that says the full one is too big.

A free-tier key may allow only a few thousand tokens in one request,
and a full request carries the instructions, the earlier chat and the
description of every tool on offer. When an AI refuses a request for
its size and there is no other AI to send it to, the loop sends a
smaller one instead of failing the run. Each level cuts more, and
loses a little more:

1. Shorter tool descriptions. The tools stay the same; the AI reads
   less about each one.
2. Only the current request. Earlier turns of the chat are left out.
3. Shorter tool results. A long page or sheet read earlier in the run
   is cut to its beginning.

The real conversation is never changed. These functions return copies,
so the saved history, the run view and any later step still see it all.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from app.agent.providers.base import Message, Role, ToolSchema

MAX_LEVEL = 3

TOOL_DESCRIPTION_CHARS = 160
PARAMETER_DESCRIPTION_CHARS = 60
TOOL_RESULT_CHARS = 1200
OLD_RESULT_CHARS = 1500

_FIRST_SENTENCE = re.compile(r"^(.+?[.!?])(\s|$)", re.DOTALL)


def estimate_tokens(messages: list[Message], tools: list[ToolSchema] | None = None) -> int:
    """A rough size: about four characters to a token. Good enough to
    report how much a level saved, not to bill anyone."""
    chars = sum(len(m.content or "") for m in messages)
    chars += sum(len(str(c.arguments)) for m in messages for c in m.tool_calls)
    chars += sum(len(t.name) + len(t.description) + len(str(t.parameters)) for t in tools or [])
    return chars // 4


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _short_description(text: str) -> str:
    """The first sentence, kept to a sensible length."""
    flat = " ".join(text.split())
    match = _FIRST_SENTENCE.match(flat)
    return _shorten(match.group(1) if match else flat, TOOL_DESCRIPTION_CHARS)


def _slim_schema(schema: Any) -> Any:
    """A JSON schema with titles dropped and descriptions shortened.

    Names, types, enums and `required` are kept exactly: they are what
    makes a call valid. `properties` maps field names to schemas, so a
    field that happens to be called "description" is left alone.
    """
    if isinstance(schema, list):
        return [_slim_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key == "description" and isinstance(value, str):
            out[key] = _shorten(value, PARAMETER_DESCRIPTION_CHARS)
        elif key in ("properties", "$defs", "definitions") and isinstance(value, dict):
            out[key] = {name: _slim_schema(sub) for name, sub in value.items()}
        elif key in ("items", "anyOf", "oneOf", "allOf", "additionalProperties"):
            out[key] = _slim_schema(value)
        else:
            out[key] = value
    return out


def slim_tools(tools: list[ToolSchema]) -> list[ToolSchema]:
    return [
        ToolSchema(
            name=t.name,
            description=_short_description(t.description),
            parameters=_slim_schema(t.parameters),
        )
        for t in tools
    ]


def compact_old_results(messages: list[Message]) -> list[Message]:
    """Tool results from earlier steps, cut to their beginning.

    Every step re-sends the whole conversation, so a page read at step 2
    is paid for again at steps 3, 4, 5 and so on. The model has already
    used it by the next step, so only the results since the last model
    reply stay whole. Copies, like the rest of this module.
    """
    last_reply = max((i for i, m in enumerate(messages) if m.role is Role.ASSISTANT), default=-1)

    def old_and_long(i: int, m: Message) -> bool:
        return (
            i < last_reply
            and m.role is Role.TOOL
            and bool(m.content)
            and len(m.content) > OLD_RESULT_CHARS
        )

    return [
        replace(m, content=m.content[:OLD_RESULT_CHARS] + "\n[shortened: already read]")
        if old_and_long(i, m)
        else m
        for i, m in enumerate(messages)
    ]


def slim_messages(messages: list[Message], level: int) -> list[Message]:
    """The same conversation, cut down to `level`. Level 0 or 1 sends it as it is."""
    if level < 2:
        return messages

    # Keep the instructions, then everything from the person's latest
    # request on: that request, and the tool calls made to answer it.
    last_user = max((i for i, m in enumerate(messages) if m.role is Role.USER), default=None)
    if last_user is None:
        kept = list(messages)
    else:
        kept = [m for m in messages[:last_user] if m.role is Role.SYSTEM] + messages[last_user:]

    if level < 3:
        return kept
    return [
        replace(m, content=m.content[:TOOL_RESULT_CHARS] + "\n[shortened]")
        if m.role is Role.TOOL and m.content and len(m.content) > TOOL_RESULT_CHARS
        else m
        for m in kept
    ]
