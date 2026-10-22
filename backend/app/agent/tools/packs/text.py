"""Plain text utilities.

Counting, pulling out structured bits, and comparing two versions are
things a model does badly by eye and a few lines of code do exactly.
The reviewer uses them to check a draft against its source; the report
writer uses them to hit a length. Read only, needs nothing connected.
"""

from __future__ import annotations

import difflib
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import register

MAX_TEXT_CHARS = 100_000
MAX_DIFF_LINES = 200
WORDS_PER_MINUTE = 200

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?")
_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")


class Operation(StrEnum):
    STATS = "stats"
    EXTRACT = "extract"
    COMPARE = "compare"


class Extract(StrEnum):
    EMAILS = "emails"
    URLS = "urls"
    NUMBERS = "numbers"


class TextToolsArgs(BaseModel):
    operation: Operation = Field(
        description="stats: counts and reading time. extract: pull out emails, urls or "
        "numbers. compare: show what changed between text and other_text."
    )
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    other_text: str | None = Field(
        default=None, max_length=MAX_TEXT_CHARS, description="The second text, for compare"
    )
    kind: Extract | None = Field(default=None, description="What to pull out, for extract")

    @model_validator(mode="after")
    def _needs(self) -> TextToolsArgs:
        if self.operation is Operation.COMPARE and not self.other_text:
            raise ValueError("compare needs other_text")
        if self.operation is Operation.EXTRACT and self.kind is None:
            raise ValueError("extract needs kind: emails, urls or numbers")
        return self


def _stats(text: str) -> dict[str, Any]:
    words = re.findall(r"\b[\w'-]+\b", text)
    sentences = len(_SENTENCE_END.findall(text)) or (1 if text.strip() else 0)
    paragraphs = len([p for p in re.split(r"\n\s*\n", text) if p.strip()])
    return {
        "characters": len(text),
        "words": len(words),
        "sentences": sentences,
        "paragraphs": paragraphs,
        "reading_minutes": round(len(words) / WORDS_PER_MINUTE, 1),
    }


def _extract(text: str, kind: Extract) -> dict[str, Any]:
    pattern = {Extract.EMAILS: _EMAIL, Extract.URLS: _URL, Extract.NUMBERS: _NUMBER}[kind]
    found = list(dict.fromkeys(m.group(0).rstrip(".,;") for m in pattern.finditer(text)))
    return {"kind": kind.value, "count": len(found), "items": found[:200]}


def _compare(old: str, new: str) -> dict[str, Any]:
    ratio = difflib.SequenceMatcher(None, old, new).ratio()
    diff = list(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), "text", "other_text", lineterm="", n=0
        )
    )
    return {
        "identical": old == new,
        "similarity": round(ratio, 3),
        "diff": diff[:MAX_DIFF_LINES],
        "diff_truncated": len(diff) > MAX_DIFF_LINES,
    }


@register
class TextTools(Tool):
    name = "text_tools"
    pack = "text"
    description = (
        "Work on text exactly: count words and sentences (stats), pull out emails, links "
        "or numbers (extract), or show what changed between two versions (compare). Use "
        "it to check length, find figures to verify, or review a revision."
    )
    args_model = TextToolsArgs
    side_effect = SideEffect.READ
    timeout_s = 10.0

    async def run(self, ctx: ToolContext, args: TextToolsArgs) -> ToolResult:  # type: ignore[override]
        if args.operation is Operation.STATS:
            return ToolResult.success(_stats(args.text))
        if args.operation is Operation.EXTRACT:
            assert args.kind is not None
            return ToolResult.success(_extract(args.text, args.kind))
        assert args.other_text is not None
        return ToolResult.success(_compare(args.text, args.other_text))
