"""An agent's tools are worked out from what its instructions say."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.tool_infer import BASICS, NEVER_GIVEN, infer_tools
from app.agent.tools.registry import registry
from app.services.agent_service import AgentService

SHEETS = {"sheets_create", "sheets_read", "sheets_append_rows", "sheets_update_cells"}


def test_a_research_agent_that_fills_an_excel_sheet_gets_search_and_sheet_tools() -> None:
    tools = set(
        infer_tools(
            "Developer Meetup Scout",
            "Find free developer meetups in Chennai and create an Excel sheet, then update it.",
        )
    )
    assert {"web_search", "get_webpage"} <= tools
    assert SHEETS <= tools
    assert set(BASICS) <= tools


def test_it_does_not_hand_out_tools_the_job_never_mentions() -> None:
    tools = set(infer_tools("Keep a spreadsheet of my monthly expenses up to date."))
    assert SHEETS <= tools
    assert not any(t.startswith(("gmail", "github", "outlook")) for t in tools)
    assert "send_email" not in tools and "gmail_send" not in tools


def test_sending_mail_is_given_only_when_the_words_ask_for_it() -> None:
    reads = set(infer_tools("Summarise my unread Gmail each morning."))
    assert {"gmail_search", "gmail_read"} <= reads
    assert "gmail_send" not in reads

    sends = set(infer_tools("Read my Gmail and reply to customers by sending an email."))
    assert "gmail_send" in sends


def test_github_work_gets_the_reading_tools_and_only_asked_for_writes() -> None:
    tools = set(infer_tools("Review each open pull request in our repo and list the risky ones."))
    assert {"github_pr_diff", "github_list_issues"} <= tools
    assert "github_comment" not in tools


def test_a_job_with_no_clue_still_gets_something_useful() -> None:
    assert {"web_search", "get_webpage"} <= set(infer_tools("Help me with things."))


def test_every_tool_named_is_a_real_one_and_never_a_chat_only_tool() -> None:
    real = {t.name for t in registry.all()}
    everything = " ".join(
        [
            "web search research excel gmail send email outlook calendar add event drive github "
            "pull request comment on the issue open an issue database sql python analyse report "
            "remember outlook calendar onedrive"
        ]
    )
    tools = infer_tools(everything)
    assert set(tools) <= real
    assert not set(tools) & NEVER_GIVEN


def test_it_gives_the_same_answer_every_time() -> None:
    text = "Find events online and add them to a sheet."
    assert infer_tools(text) == infer_tools(text)


def _agent(**kw: object) -> SimpleNamespace:
    base = {
        "name": "Scout",
        "description": "",
        "instructions": "Search the web for meetups and add them to a Google Sheet.",
        "tools": None,
        "tools_auto": False,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_an_agent_with_no_list_gets_one_and_is_marked_automatic() -> None:
    agent = _agent()
    AgentService.choose_tools(agent)  # type: ignore[arg-type]
    assert agent.tools_auto is True
    assert SHEETS <= set(agent.tools or [])


def test_an_automatic_list_follows_the_instructions_when_they_change() -> None:
    agent = _agent()
    AgentService.choose_tools(agent)  # type: ignore[arg-type]
    agent.instructions = "Read my Gmail and draft replies."
    AgentService.choose_tools(agent, refresh=True)  # type: ignore[arg-type]
    assert "gmail_search" in (agent.tools or [])
    assert not SHEETS & set(agent.tools or [])


@pytest.mark.parametrize("refresh", [False, True])
def test_a_list_chosen_by_hand_is_never_touched(refresh: bool) -> None:
    agent = _agent(tools=["calculator"], tools_auto=False)
    AgentService.choose_tools(agent, refresh=refresh)  # type: ignore[arg-type]
    assert agent.tools == ["calculator"] and agent.tools_auto is False


@pytest.mark.parametrize(
    ("connected", "reads", "send"),
    [
        (None, "gmail_search", "gmail_send"),
        ({"microsoft"}, "outlook_search", "outlook_send"),
        ({"email"}, "list_emails", "send_email"),
        ({"google", "microsoft"}, "gmail_search", "gmail_send"),
    ],
)
def test_my_email_means_the_mail_app_the_person_connected(
    connected: set[str] | None, reads: str, send: str
) -> None:
    quiet = infer_tools("Summarise my unread email every morning.", connected=connected)
    assert reads in quiet and send not in quiet
    loud = infer_tools("Read my email and reply to each customer.", connected=connected)
    assert send in loud


def test_calendar_and_files_follow_the_connected_app_too() -> None:
    tools = set(
        infer_tools("Schedule a meeting and attach the right documents.", connected={"microsoft"})
    )
    assert {"outlook_calendar_list", "outlook_calendar_create", "onedrive_read"} <= tools
    assert not {"google_calendar_create", "google_drive_read"} & tools


def test_a_named_vendor_wins_over_the_connected_one() -> None:
    tools = set(infer_tools("Check my Gmail for invoices.", connected={"microsoft"}))
    assert "gmail_search" in tools and "outlook_search" not in tools


def test_reading_a_sheet_does_not_give_the_right_to_change_it() -> None:
    tools = set(infer_tools("Read my sheet of leads and summarise it."))
    assert "sheets_read" in tools
    assert not {"sheets_create", "sheets_append_rows", "sheets_update_cells"} & tools


def test_everyday_words_do_not_bring_database_or_github_tools() -> None:
    tools = set(infer_tools("Make a table of any issues customers raise in the chat."))
    assert not {"run_query", "list_tables"} & tools
    assert not any(t.startswith("github") for t in tools)


def test_running_on_a_schedule_is_not_booking_a_meeting() -> None:
    tools = set(infer_tools("On a schedule every morning, list my calendar events."))
    assert "google_calendar_list" in tools
    assert "google_calendar_create" not in tools
    assert "web_search" not in tools  # "events" here are calendar events


def test_every_agent_can_recall_what_it_was_told_but_saves_only_when_asked() -> None:
    assert "recall" in infer_tools("Help me with things.")
    assert "remember" not in infer_tools("Help me with things.")
    assert "remember" in infer_tools("Remember my preferences for next time.")


@pytest.mark.parametrize(
    ("words", "connected", "wanted", "not_wanted"),
    [
        ("Reschedule my 3pm meeting to Friday.", None, {"google_calendar_update"}, set()),
        (
            "Cancel every meeting in my calendar on Friday.",
            {"microsoft"},
            {"outlook_calendar_cancel"},
            {"google_calendar_cancel"},
        ),
        (
            "List my calendar for the week.",
            None,
            {"google_calendar_list"},
            {"google_calendar_update", "google_calendar_cancel"},
        ),
        ("Archive newsletters in my inbox and label invoices.", None, {"gmail_organize"}, set()),
        ("Archive newsletters in my inbox.", {"microsoft"}, {"outlook_organize"}, set()),
        ("Post a summary to Slack every evening.", None, {"slack_post"}, {"teams_post"}),
        ("Post the summary to our Microsoft Teams channel.", None, {"teams_post"}, set()),
        ("My teams are busy this week.", None, set(), {"teams_post"}),
        (
            "Add new leads to the Excel workbook in OneDrive.",
            None,
            {"excel_read", "excel_append_rows"},
            {"sheets_append_rows"},
        ),
        (
            "Keep my expenses spreadsheet up to date.",
            {"microsoft"},
            {"excel_append_rows"},
            {"sheets_append_rows"},
        ),
        (
            "Reschedule my Outlook calendar meeting.",
            {"google"},
            {"outlook_calendar_update"},
            {"outlook_search", "google_calendar_update"},
        ),
    ],
)
def test_the_new_tools_come_with_the_words_that_need_them(
    words: str, connected: set[str] | None, wanted: set[str], not_wanted: set[str]
) -> None:
    tools = set(infer_tools(words, connected=connected))
    assert wanted <= tools, wanted - tools
    assert not not_wanted & tools, not_wanted & tools
