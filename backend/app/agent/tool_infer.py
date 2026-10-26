"""Choosing an agent's tools from what its instructions say.

Nobody should have to read a list of forty tool names to make an agent.
A person writes "find free meetups and add them to a Google Sheet", and
the agent gets exactly the tools that job needs: search the web, read a
page, and create, read and add to a sheet. Nothing more, so a run on its
own is limited to what its job needs.

The rules are plain words matched against the instructions. That is on
purpose: it costs no model call, gives the same answer every time, and
can be read and tested. Writing tools are added only when the words ask
for the action ("send", "add", "create", "update"). Reading tools come
with the app being named.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# Never part of an agent's own toolbox: they exist for one chat only.
NEVER_GIVEN = {"propose_agent", "ask_specialist"}

# Always useful, never harmful: dates, exact sums and text checks.
BASICS = ["current_time", "calculator", "text_tools"]

# When nothing in the words points at an app, a research agent is the
# most useful guess: it can look things up and read what it finds.
FALLBACK = ["web_search", "get_webpage"]


def _has(pattern: str) -> Callable[[str], bool]:
    rx = re.compile(pattern, re.IGNORECASE)
    return lambda text: bool(rx.search(text))


_ACTS = r"(send|reply|respond|email (them|it|the)|forward)"
_WRITES = r"(add|append|create|make|update|write|save|record|log|fill|insert|put|maintain|keep)"

# (matches the words, tools it brings)
_RULES: list[tuple[Callable[[str], bool], list[str]]] = [
    # The web
    (
        _has(
            r"\b(web|website|search|research|look ?up|find|news|online|internet|google it|"
            r"events?|meet-?ups?|hackathons?|conferences?|price|compare|trend|article|blog|link)\b"
        ),
        ["web_search", "get_webpage"],
    ),
    (_has(r"https?://|\b(web ?page|url|read the (page|site))\b"), ["get_webpage"]),
    # Spreadsheets. "Excel" means a Google Sheet here: that is what we can edit.
    (
        _has(r"\b(excel|spread-?sheets?|work-?sheets?|google sheets?|sheets?|csv|xlsx|tabular)\b"),
        ["sheets_create", "sheets_read", "sheets_append_rows", "sheets_update_cells"],
    ),
    # Google mail
    (_has(r"\b(gmail|google mail)\b"), ["gmail_search", "gmail_read", "gmail_create_draft"]),
    (
        _has(rf"\b(gmail|google mail)\b.*\b{_ACTS}\b|\b{_ACTS}\b.*\b(gmail|google mail)\b"),
        ["gmail_send"],
    ),
    # Outlook
    (
        _has(r"\b(outlook|microsoft mail|office ?365)\b"),
        ["outlook_search", "outlook_read", "outlook_create_draft"],
    ),
    (
        _has(
            rf"\b(outlook|microsoft mail)\b.*\b{_ACTS}\b|\b{_ACTS}\b.*\b(outlook|microsoft mail)\b"
        ),
        ["outlook_send"],
    ),
    # Mail with no vendor named: the connected Google account is the common case.
    (
        _has(r"\b(e-?mails?|inbox|unread|newsletter|messages? from)\b"),
        ["gmail_search", "gmail_read", "gmail_create_draft"],
    ),
    # Calendars
    (
        _has(r"\b(calendar|meeting|appointment|agenda|schedule a|book a)\b"),
        ["google_calendar_list"],
    ),
    (
        _has(
            rf"\b(calendar|meeting|appointment)\b.*\b{_WRITES}\b|\b{_WRITES}\b.*\b(calendar|meeting|appointment)\b"
        ),
        ["google_calendar_create"],
    ),
    (_has(r"\boutlook calendar\b"), ["outlook_calendar_list", "outlook_calendar_create"]),
    # Files
    (
        _has(r"\b(drive|google docs?|documents?|files?|folder)\b"),
        ["google_drive_search", "google_drive_read"],
    ),
    (_has(r"\bonedrive\b"), ["onedrive_search", "onedrive_read"]),
    # Code
    (
        _has(
            r"\b(github|repo(sitory)?|pull request|\bpr\b|commits?|issues?|code review|"
            r"ci\b|build fail)\b"
        ),
        [
            "github_list_repos",
            "github_search_code",
            "github_read_file",
            "github_list_issues",
            "github_read_issue",
            "github_pr_diff",
            "github_list_commits",
            "github_ci_status",
        ],
    ),
    (_has(r"\b(comment on|reply to) (the )?(issue|pull request|pr)\b"), ["github_comment"]),
    (_has(r"\b(open|file|create|raise) (an? )?(github )?issue\b"), ["github_create_issue"]),
    (
        _has(r"\b(fix|patch|propose|pull request|refactor)\b.*\b(code|repo|bug)\b"),
        ["github_propose_change"],
    ),
    # Data
    (
        _has(r"\b(database|sql|query|tables?|postgres|mysql)\b"),
        ["list_tables", "describe_table", "run_query"],
    ),
    (
        _has(
            r"\b(analy[sz]e|statistic|average|median|correlat|forecast|chart|data ?set|"
            r"pandas|python)\b"
        ),
        ["python_run"],
    ),
    # Writing up
    (_has(r"\b(report|summary|summari[sz]e|write ?up|brief|digest)\b"), ["report_write"]),
    # Memory
    (_has(r"\b(remember|memory|last time|previous(ly)?|preferences?)\b"), ["recall", "remember"]),
]


def infer_tools(*texts: str, available: set[str] | None = None) -> list[str]:
    """The tools a job needs, from the words that describe it.

    `available` limits the answer to tools that exist (the registry's
    names, when not given), so a rule can never name a tool that is gone.
    Order is stable: basics first, then in the order of the rules.
    """
    if available is None:
        from app.agent.tools.registry import registry

        available = {t.name for t in registry.all()}

    text = " ".join(t for t in texts if t).strip()
    wanted: list[str] = list(BASICS)
    matched = False
    for test, tools in _RULES:
        if test(text):
            matched = True
            wanted.extend(tools)
    if not matched:
        wanted.extend(FALLBACK)

    return [t for t in dict.fromkeys(wanted) if t in available and t not in NEVER_GIVEN]
