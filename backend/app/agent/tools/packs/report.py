"""Assemble a report.

The report agent's tool. It does not write the content, the model does;
it turns sections into one well-formed Markdown document and says what
is missing, so a report cannot silently go out without sources. It only
builds text, so it changes nothing in the world. Needs nothing connected.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import register

MAX_SECTIONS = 30
MAX_SECTION_CHARS = 20_000


class Section(BaseModel):
    heading: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=MAX_SECTION_CHARS, description="Markdown")


class ReportWriteArgs(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(
        min_length=1, max_length=2000, description="Two to four sentences: the answer first"
    )
    sections: list[Section] = Field(min_length=1, max_length=MAX_SECTIONS)
    sources: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Where the facts came from: addresses or document names",
    )


def build_markdown(args: ReportWriteArgs, *, today: str) -> str:
    lines = [
        f"# {args.title.strip()}",
        "",
        f"*{today}*",
        "",
        "## Summary",
        "",
        args.summary.strip(),
    ]
    for section in args.sections:
        lines += ["", f"## {section.heading.strip()}", "", _demote(section.body.strip())]
    sources = [s.strip() for s in args.sources if s.strip()]
    if sources:
        lines += ["", "## Sources", "", *[f"- {s}" for s in sources]]
    return "\n".join(lines) + "\n"


def _demote(body: str) -> str:
    """A section body must not start its own top-level headings, or the
    report would have two titles. Push them down to third level."""
    return re.sub(r"^#{1,2}\s", "### ", body, flags=re.MULTILINE)


@register
class ReportWrite(Tool):
    name = "report_write"
    pack = "report"
    description = (
        "Assemble the final report as one Markdown document from a title, a short "
        "summary, sections and sources. Call it once, when the content is ready. It "
        "returns the finished document and a list of anything still missing."
    )
    args_model = ReportWriteArgs
    side_effect = SideEffect.READ
    timeout_s = 10.0

    async def run(self, ctx: ToolContext, args: ReportWriteArgs) -> ToolResult:  # type: ignore[override]
        markdown = build_markdown(args, today=datetime.now(UTC).strftime("%d %B %Y"))
        missing: list[str] = []
        if not any(s.strip() for s in args.sources):
            missing.append("sources: nothing says where the facts came from")
        return ToolResult.success(
            {
                "markdown": markdown,
                "words": len(markdown.split()),
                "sections": len(args.sections),
                "missing": missing,
            }
        )
