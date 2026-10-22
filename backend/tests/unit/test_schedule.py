"""When an agent runs on its own: the schedule and its next time."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.agent.schedule import Schedule, describe, next_run

IST = ZoneInfo("Asia/Kolkata")


def at(*args: int, tz: ZoneInfo = UTC) -> datetime:
    return datetime(*args, tzinfo=tz)


def test_a_daily_schedule_fires_at_the_chosen_time_in_the_persons_zone() -> None:
    schedule = Schedule(frequency="daily", time="23:30", timezone="Asia/Kolkata")
    # 20:00 IST on the 21st: the next run is 23:30 IST the same day, 18:00 UTC.
    assert next_run(schedule, at(2026, 10, 21, 20, 0, tz=IST)) == at(2026, 10, 21, 18, 0)


def test_after_todays_time_the_next_run_is_tomorrow() -> None:
    schedule = Schedule(frequency="daily", time="06:00", timezone="Asia/Kolkata")
    assert next_run(schedule, at(2026, 10, 21, 7, 0, tz=IST)) == at(2026, 10, 22, 0, 30)


def test_the_exact_moment_does_not_fire_twice() -> None:
    schedule = Schedule(frequency="daily", time="06:00", timezone="Asia/Kolkata")
    assert next_run(schedule, at(2026, 10, 21, 6, 0, tz=IST)) == at(2026, 10, 22, 0, 30)


def test_weekdays_skip_the_weekend() -> None:
    schedule = Schedule(frequency="weekdays", time="09:00", timezone="UTC")
    friday_evening = at(2026, 10, 23, 18, 0)  # a Friday
    assert next_run(schedule, friday_evening) == at(2026, 10, 26, 9, 0)  # Monday


def test_weekly_runs_only_on_the_chosen_days() -> None:
    schedule = Schedule(frequency="weekly", time="08:00", days=[3, 0], timezone="UTC")
    assert schedule.days == [0, 3]
    monday_noon = at(2026, 10, 19, 12, 0)  # a Monday, past 08:00
    assert next_run(schedule, monday_noon) == at(2026, 10, 22, 8, 0)  # Thursday


def test_wall_clock_time_holds_across_a_daylight_saving_change() -> None:
    london = ZoneInfo("Europe/London")
    schedule = Schedule(frequency="daily", time="09:00", timezone="Europe/London")
    # Clocks go back on 25 October 2026. 09:00 stays 09:00 local.
    before = next_run(schedule, at(2026, 10, 23, 12, 0, tz=london))  # Saturday 24th, BST
    after = next_run(schedule, before)  # Sunday 25th, GMT
    assert before.astimezone(london).hour == 9
    assert after.astimezone(london).hour == 9
    # 25 hours apart in real time: the clock hour is held, not the interval.
    assert (after - before).total_seconds() == 25 * 3600
    assert before.hour == 8 and after.hour == 9  # in UTC terms


@pytest.mark.parametrize(
    "bad",
    [
        {"time": "25:00"},
        {"time": "9am"},
        {"time": "23:60"},
        {"timezone": "Mars/Olympus"},
        {"frequency": "weekly"},  # no days
        {"frequency": "weekly", "days": [7]},
        {"frequency": "hourly"},
    ],
)
def test_a_schedule_that_cannot_run_is_refused(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Schedule(**bad)


def test_days_are_ignored_unless_weekly() -> None:
    assert Schedule(frequency="daily", days=[1, 2]).days == []


def test_it_reads_back_in_plain_words() -> None:
    assert describe(Schedule(time="23:30")) == "Every day at 11:30 PM (Asia/Kolkata)"
    assert describe(Schedule(frequency="weekdays", time="06:05", timezone="UTC")) == (
        "Monday to Friday at 6:05 AM (UTC)"
    )
    assert describe(Schedule(frequency="weekly", time="12:00", days=[0, 2, 4], timezone="UTC")) == (
        "Every Monday, Wednesday and Friday at 12:00 PM (UTC)"
    )
