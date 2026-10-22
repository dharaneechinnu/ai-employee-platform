"""The date and time.

A model does not know what day it is, and an agent that works from
dates ("events today or later") needs the real one, in the person's own
time zone. Read only, and needs nothing connected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import register

DEFAULT_ZONE = "Asia/Kolkata"


class CurrentTimeArgs(BaseModel):
    timezone: str = Field(
        default=DEFAULT_ZONE,
        description="An IANA time zone such as Asia/Kolkata or Europe/London",
        max_length=60,
    )


@register
class CurrentTime(Tool):
    name = "current_time"
    pack = "clock"
    description = (
        "Get today's date and the time now, in a time zone. Use it whenever the answer "
        "depends on today's date, for example to tell upcoming from past."
    )
    args_model = CurrentTimeArgs
    side_effect = SideEffect.READ
    timeout_s = 5.0

    async def run(self, ctx: ToolContext, args: CurrentTimeArgs) -> ToolResult:  # type: ignore[override]
        try:
            zone = ZoneInfo(args.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ToolResult.failure(
                "invalid_timezone", f"'{args.timezone}' is not a time zone name I know."
            )
        now = datetime.now(UTC).astimezone(zone)
        return ToolResult.success(
            {
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M"),
                "weekday": now.strftime("%A"),
                "timezone": args.timezone,
                "iso": now.isoformat(timespec="minutes"),
            }
        )
