"""The six agents: each sees its own tools, and only ones it may use."""

import app.agent.tools.packs  # noqa: F401  (registers every tool)
from app.agent.team import ROLES, specialist_tools
from app.agent.tools.base import SideEffect
from app.agent.tools.registry import registry


def offered(role_key: str) -> set[str]:
    return {t.name for t in specialist_tools(registry.all(), ROLES[role_key])}


def test_the_roster_has_the_six_agents() -> None:
    assert set(ROLES) == {"researcher", "analyst", "writer", "critic", "developer", "generalist"}


def test_every_named_tool_exists() -> None:
    """A typo in a role's list would silently leave it without that tool."""
    for role in ROLES.values():
        for name in role.tools or ():
            assert registry.get(name) is not None, f"{role.key}: no tool called {name}"
        for pack in role.packs:
            assert any(t.pack == pack for t in registry.all()), f"{role.key}: no pack {pack}"


def test_no_agent_can_change_anything() -> None:
    """Agents work inside the lead's step and cannot ask a person, so they only look."""
    for key in ROLES:
        for tool in specialist_tools(registry.all(), ROLES[key]):
            assert tool.side_effect is SideEffect.READ, f"{key} has {tool.name}"


def test_nobody_gets_python_or_team_tools() -> None:
    for key in ROLES:
        names = offered(key)
        assert "python_run" not in names  # runs code: lead only, with approval
        assert "ask_specialist" not in names  # depth 1


def test_each_agent_has_its_own_tools() -> None:
    assert {"calculator", "text_tools"} <= offered("analyst")
    assert "report_write" in offered("writer")
    assert "report_write" not in offered("critic")
    assert "web_search" not in offered("writer")
    assert {"calculator", "text_tools", "get_webpage"} <= offered("critic")
    assert "gmail_search" not in offered("critic")


def test_the_analyst_reads_data_wherever_the_person_keeps_it() -> None:
    assert {"sheets_read", "google_drive_read", "onedrive_read"} <= offered("analyst")
    assert {"list_tables", "describe_table", "run_query"} <= offered("analyst")


def test_the_developer_can_look_up_an_error_on_the_web() -> None:
    assert {"web_search", "get_webpage"} <= offered("developer")


def test_the_developer_reads_github_and_the_researcher_does_not_have_to() -> None:
    github = {
        t.name for t in registry.all() if t.pack == "github" and t.side_effect is SideEffect.READ
    }
    assert github
    assert github <= offered("developer")
    assert "web_search" in offered("researcher")


def test_the_generalist_gets_every_read_tool() -> None:
    reads = {
        t.name
        for t in registry.all()
        if t.side_effect is SideEffect.READ and t.pack not in {"memory", "team"}
    }
    assert offered("generalist") == reads
