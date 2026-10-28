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
from collections.abc import Callable, Mapping

# Never part of an agent's own toolbox: they exist for one chat only.
NEVER_GIVEN = {"propose_agent", "ask_specialist"}

# Always useful, never harmful: dates, exact sums, text checks, and what
# the person has told the assistant before (their tone, their sheet, the
# people they mean), so an agent does not ask for it again.
BASICS = ["current_time", "calculator", "text_tools", "recall"]

# When nothing in the words points at an app, a research agent is the
# most useful guess: it can look things up and read what it finds.
FALLBACK = ["web_search", "get_webpage"]

Connected = set[str] | None
Pick = list[str] | Callable[[Connected], list[str]]


def _has(pattern: str) -> Callable[[str], bool]:
    rx = re.compile(pattern, re.IGNORECASE)
    return lambda text: bool(rx.search(text))


def _unless(test: Callable[[str], bool], named: str) -> Callable[[str], bool]:
    """A generic rule that stands aside when the words name the app."""
    vendor = _has(rf"\b{named}\b")
    return lambda text: test(text) and not vendor(text)


def _both(first: str, second: str) -> Callable[[str], bool]:
    """The two kinds of words in either order, e.g. "sheet ... add"."""
    return _has(rf"\b{first}\b.*\b{second}\b|\b{second}\b.*\b{first}\b")


_ACTS = r"(send|reply|respond|email (them|it|the)|forward)"
_WRITES = r"(add|append|create|make|update|write|save|record|log|fill|insert|put|maintain|keep)"
_SHEET = r"(excel|spread-?sheets?|work-?sheets?|google sheets?|sheets?|csv|xlsx|tabular)"
_MAIL = r"(e-?mails?|inbox|unread|newsletter|messages? from|mail)"
_CALENDAR = r"(calendar|meetings?|appointments?|agenda|schedule a|book a)"
_BOOKS = rf"({_WRITES[1:-1]}|book|set up|arrange|invite)"
_FILES = r"(documents?|files?|folders?|docs)"
# Words that name a vendor, so the generic rules for that area stand aside.
_NAMES_SHEET = r"(google sheets?|onedrive|microsoft|office ?365)"
_NAMES_MAIL = (
    r"(gmail|google mail|outlook|microsoft mail|office ?365|imap|mailbox|mail server|zoho|"
    r"yahoo mail)"
)
_NAMES_CALENDAR = r"(google calendar|outlook calendar)"
_NAMES_FILES = r"(google drive|google docs?|onedrive|sharepoint|word documents?)"
_TIDY = (
    r"(archive|label|tidy|clean ?up|organi[sz]e|sort|mark (them |it |as )*(read|unread)|star|flag)"
)
_MOVES = r"(move|reschedule|change|shift|postpone|push back|bring forward|update)"
_CANCELS = r"(cancel|delete|remove|call off)"

# The app that answers "my email", "my calendar" and "my files" when the
# words name no vendor: the one the person has connected, Google first.
# With nothing connected (or not known) it is Google, the common case, and
# the readiness check then says plainly what to connect.
# Each app: (reading, sending, tidying).
_MAIL_APPS = {
    "google": (
        ["gmail_search", "gmail_read", "gmail_create_draft"],
        ["gmail_send"],
        ["gmail_organize"],
    ),
    "microsoft": (
        ["outlook_search", "outlook_read", "outlook_create_draft"],
        ["outlook_send"],
        ["outlook_organize"],
    ),
    "email": (["list_emails", "read_email", "save_draft"], ["send_email"], []),
}
# Each app: (looking, adding, moving, cancelling).
_CALENDAR_APPS = {
    "google": (
        ["google_calendar_list"],
        ["google_calendar_create"],
        ["google_calendar_update"],
        ["google_calendar_cancel"],
    ),
    "microsoft": (
        ["outlook_calendar_list"],
        ["outlook_calendar_create"],
        ["outlook_calendar_update"],
        ["outlook_calendar_cancel"],
    ),
}
# Each app: (reading, changing). Excel files live in OneDrive.
_SHEET_APPS = {
    "google": (["sheets_read"], ["sheets_create", "sheets_append_rows", "sheets_update_cells"]),
    "microsoft": (["excel_read"], ["excel_append_rows", "excel_update_cells"]),
}
_FILE_APPS = {
    "google": ["google_drive_search", "google_drive_read"],
    "microsoft": ["onedrive_search", "onedrive_read"],
}


def _app(connected: Connected, choices: Mapping[str, object]) -> str:
    if connected:
        for app in choices:
            if app in connected:
                return app
    return "google"


def _mail(part: int) -> Callable[[Connected], list[str]]:
    return lambda connected: _MAIL_APPS[_app(connected, _MAIL_APPS)][part]


def _calendar(part: int) -> Callable[[Connected], list[str]]:
    return lambda connected: _CALENDAR_APPS[_app(connected, _CALENDAR_APPS)][part]


def _files(connected: Connected) -> list[str]:
    return _FILE_APPS[_app(connected, _FILE_APPS)]


def _sheets(part: int) -> Callable[[Connected], list[str]]:
    return lambda connected: _SHEET_APPS[_app(connected, _SHEET_APPS)][part]


# (matches the words, tools it brings)
_RULES: list[tuple[Callable[[str], bool], Pick]] = [
    # The web
    (
        _has(
            r"\b(web|website|search|research|look ?up|find|news|online|internet|google it|"
            r"(local|public|tech|upcoming) events?|events? (in|near|around)|meet-?ups?|"
            r"hackathons?|conferences?|price|compare|trend|article|blog|link)\b"
        ),
        ["web_search", "get_webpage"],
    ),
    (_has(r"https?://|\b(web ?page|url|read the (page|site))\b"), ["get_webpage"]),
    # Spreadsheets: a Google Sheet, or an Excel workbook in OneDrive. Reading
    # comes with the sheet being named; changing it only when asked.
    (_has(r"\bgoogle sheets?\b"), _SHEET_APPS["google"][0]),
    (_both(r"google sheets?", rf"({_WRITES[1:-1]}|track|tracker)"), _SHEET_APPS["google"][1]),
    (
        _both(r"(excel|xlsx|workbook)", r"(onedrive|microsoft|office ?365)"),
        _SHEET_APPS["microsoft"][0],
    ),
    (
        lambda t: (
            _both(r"(excel|xlsx|workbook)", r"(onedrive|microsoft|office ?365)")(t)
            and _both(_SHEET, rf"({_WRITES[1:-1]}|track|tracker)")(t)
        ),
        _SHEET_APPS["microsoft"][1],
    ),
    (_unless(_has(rf"\b{_SHEET}\b"), _NAMES_SHEET), _sheets(0)),
    (_unless(_both(_SHEET, rf"({_WRITES[1:-1]}|track|tracker)"), _NAMES_SHEET), _sheets(1)),
    # Mail, by vendor when the words name one
    (_has(r"\b(gmail|google mail)\b"), _MAIL_APPS["google"][0]),
    (_both(r"(gmail|google mail)", _ACTS), _MAIL_APPS["google"][1]),
    (_both(r"(gmail|google mail)", _TIDY), _MAIL_APPS["google"][2]),
    # "Outlook" means its mail, except in "Outlook calendar".
    (_has(r"\b(outlook(?! calendar)|microsoft mail|office ?365)\b"), _MAIL_APPS["microsoft"][0]),
    (_both(r"(outlook(?! calendar)|microsoft mail)", _ACTS), _MAIL_APPS["microsoft"][1]),
    (_both(r"(outlook(?! calendar)|microsoft mail)", _TIDY), _MAIL_APPS["microsoft"][2]),
    (_has(r"\b(imap|mailbox|mail server|zoho|yahoo mail)\b"), _MAIL_APPS["email"][0]),
    (_both(r"(imap|mailbox|mail server|zoho|yahoo mail)", _ACTS), _MAIL_APPS["email"][1]),
    # ...and the connected mail app when they do not.
    (_unless(_has(rf"\b{_MAIL}\b"), _NAMES_MAIL), _mail(0)),
    (_unless(_both(_MAIL, _ACTS), _NAMES_MAIL), _mail(1)),
    (_unless(_both(_MAIL, _TIDY), _NAMES_MAIL), _mail(2)),
    # Calendars
    (_has(r"\boutlook calendar\b"), _CALENDAR_APPS["microsoft"][0]),
    (_both(r"outlook calendar", _BOOKS), _CALENDAR_APPS["microsoft"][1]),
    (_has(r"\bgoogle calendar\b"), _CALENDAR_APPS["google"][0]),
    (_both(r"google calendar", _BOOKS), _CALENDAR_APPS["google"][1]),
    (_both(r"google calendar", _MOVES), _CALENDAR_APPS["google"][2]),
    (_both(r"google calendar", _CANCELS), _CALENDAR_APPS["google"][3]),
    (_both(r"outlook calendar", _MOVES), _CALENDAR_APPS["microsoft"][2]),
    (_both(r"outlook calendar", _CANCELS), _CALENDAR_APPS["microsoft"][3]),
    (_unless(_has(rf"\b{_CALENDAR}\b"), _NAMES_CALENDAR), _calendar(0)),
    (_unless(_both(_CALENDAR, _BOOKS), _NAMES_CALENDAR), _calendar(1)),
    (_unless(_both(_CALENDAR, _MOVES), _NAMES_CALENDAR), _calendar(2)),
    (
        _unless(_has(r"\breschedul\w*\b"), _NAMES_CALENDAR),
        lambda c: _calendar(0)(c) + _calendar(2)(c),
    ),
    (_unless(_both(_CALENDAR, _CANCELS), _NAMES_CALENDAR), _calendar(3)),
    (
        _has(r"\b(schedule|book|set up|arrange) (a|an|the) (meeting|call|appointment|event)\b"),
        _calendar(1),
    ),
    # Team chat. "Teams" alone is an everyday word, so it needs Microsoft or
    # a channel with it.
    (_has(r"\bslack\b"), ["slack_post"]),
    (_has(r"\b(microsoft teams|ms teams|teams channel|(in|on|to) teams)\b"), ["teams_post"]),
    # Files
    (_has(r"\b(google drive|google docs?)\b"), _FILE_APPS["google"]),
    (_has(r"\b(onedrive|sharepoint|word documents?)\b"), _FILE_APPS["microsoft"]),
    (_unless(_has(rf"\b(drive|{_FILES[1:-1]})\b"), _NAMES_FILES), _files),
    # Code. "Issues" alone is too common a word ("any issues with my order")
    # to mean GitHub, so it needs the code context around it.
    (
        _has(
            r"\b(github|repo(sitory)?|pull requests?|prs?|commits?|code review|ci|build fail\w*|"
            r"github issues?|issue tracker|triage)\b"
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
    # Data. A bare "table" or "query" is everyday English ("a table of
    # events", "answer any query"), so it needs a database word with it.
    (
        _has(r"\b(database|sql|postgres(ql)?|mysql|sqlite|db tables?|sql query)\b"),
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
    # Memory: reading it is a basic; saving to it only when asked.
    (_has(r"\b(remember|memory|last time|previous(ly)?|preferences?)\b"), ["remember"]),
]


def infer_tools(
    *texts: str, available: set[str] | None = None, connected: Connected = None
) -> list[str]:
    """The tools a job needs, from the words that describe it.

    `available` limits the answer to tools that exist (the registry's
    names, when not given), so a rule can never name a tool that is gone.
    `connected` is the kinds of app the person has connected; it decides
    which app "my email", "my calendar" and "my files" mean.
    Order is stable: basics first, then in the order of the rules.
    """
    if available is None:
        from app.agent.tools.registry import registry

        available = {t.name for t in registry.all()}

    text = " ".join(t for t in texts if t).strip()
    wanted: list[str] = list(BASICS)
    matched = False
    for test, pick in _RULES:
        if test(text):
            matched = True
            wanted.extend(pick(connected) if callable(pick) else pick)
    if not matched:
        wanted.extend(FALLBACK)

    return [t for t in dict.fromkeys(wanted) if t in available and t not in NEVER_GIVEN]
