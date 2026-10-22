"""When an agent runs on its own.

A schedule is a time of day in the person's time zone, on every day,
on weekdays, or on chosen days of the week. Stored as plain JSON on
the agent so it is easy to show and to edit:

    {"frequency": "daily", "time": "23:30", "timezone": "Asia/Kolkata"}
    {"frequency": "weekly", "time": "09:00", "days": [0, 3], "timezone": "Europe/London"}

Days count from Monday = 0. Times are wall-clock in the zone, so
"23:30" stays 23:30 across daylight saving changes.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_ZONE = "Asia/Kolkata"
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class Schedule(BaseModel):
    frequency: Literal["daily", "weekdays", "weekly"] = "daily"
    time: str = Field(default="23:30", description="24-hour time, such as 06:00 or 23:30")
    days: list[int] = Field(default_factory=list, description="Weekly only: 0 Monday to 6 Sunday")
    timezone: str = DEFAULT_ZONE

    @field_validator("time")
    @classmethod
    def _time(cls, value: str) -> str:
        value = value.strip()
        if not _TIME.match(value):
            raise ValueError("Time must look like 06:00 or 23:30.")
        return value

    @field_validator("timezone")
    @classmethod
    def _zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"'{value}' is not a time zone name.") from exc
        return value

    @model_validator(mode="after")
    def _days(self) -> Schedule:
        if self.frequency == "weekly":
            if not self.days:
                raise ValueError("Pick at least one day of the week.")
            if any(d < 0 or d > 6 for d in self.days):
                raise ValueError("Days are 0 (Monday) to 6 (Sunday).")
            self.days = sorted(set(self.days))
        else:
            self.days = []
        return self

    def allowed_days(self) -> set[int]:
        if self.frequency == "weekdays":
            return {0, 1, 2, 3, 4}
        if self.frequency == "weekly":
            return set(self.days)
        return set(range(7))


def next_run(schedule: Schedule, after: datetime) -> datetime:
    """The first moment after `after` this schedule fires, in UTC."""
    zone = ZoneInfo(schedule.timezone)
    local = after.astimezone(zone)
    hour, minute = (int(part) for part in schedule.time.split(":"))
    allowed = schedule.allowed_days()
    for offset in range(9):
        day = (local + timedelta(days=offset)).date()
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        if candidate > local and candidate.weekday() in allowed:
            return candidate.astimezone(UTC)
    raise ValueError("A schedule with no allowed days never runs.")  # pragma: no cover


def describe(schedule: Schedule) -> str:
    """One plain sentence: "Every day at 11:30 PM (Asia/Kolkata)"."""
    hour, minute = (int(part) for part in schedule.time.split(":"))
    clock = f"{hour % 12 or 12}:{minute:02d} {'PM' if hour >= 12 else 'AM'}"
    if schedule.frequency == "daily":
        when = "Every day"
    elif schedule.frequency == "weekdays":
        when = "Monday to Friday"
    else:
        names = [WEEKDAY_NAMES[d] for d in schedule.days]
        when = "Every " + (
            names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        )
    return f"{when} at {clock} ({schedule.timezone})"
