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
