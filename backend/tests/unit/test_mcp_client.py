"""The MCP client and the tools built from a server's list."""

from __future__ import annotations

import pytest

import app.agent.mcp.client as mcp_client
from app.agent.mcp.client import McpClient, McpError
from app.agent.mcp.tools import build_tools, describe, tool_name
from app.agent.tools.base import Grant, SideEffect, ToolContext
from tests.fake_mcp import FakeMcpServer

URL = "https://crm.example.com/mcp"


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeMcpServer:
    fake = FakeMcpServer()
    monkeypatch.setattr(mcp_client, "transport", fake.transport)
    return fake


@pytest.mark.parametrize("sse", [False, True])
async def test_lists_and_calls_tools_over_json_and_event_streams(
    monkeypatch: pytest.MonkeyPatch, sse: bool
) -> None:
    fake = FakeMcpServer(sse=sse)
    monkeypatch.setattr(mcp_client, "transport", fake.transport)

    async with McpClient(URL) as client:
        tools = await client.list_tools()
        result = await client.call_tool("find_customer", {"query": "Asha"})

    assert [t["name"] for t in tools] == ["find_customer", "update_deal_stage", "delete_contact"]
    assert "Asha Rao" in result["content"][0]["text"]
    # The session id from initialize is repeated on every later request.
    assert fake.session_headers == [None, "sess-123", "sess-123"]


async def test_a_wrong_token_is_reported_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeMcpServer(token="right-token")
    monkeypatch.setattr(mcp_client, "transport", fake.transport)

    with pytest.raises(McpError) as caught:
        async with McpClient(URL, token="wrong-token"):
            pass
    assert caught.value.error_class == "auth_failed"


def test_effects_come_from_the_servers_own_labels() -> None:
    from tests.fake_mcp import TOOLS

    effects = {t["name"]: t["effect"] for t in (describe(raw) for raw in TOOLS) if t}
    assert effects == {
        "find_customer": "read",
        # Unlabelled means "ask a person first", not "harmless".
        "update_deal_stage": "write",
        "delete_contact": "destructive",
    }
    # Gemini rejects `$schema`, so it is stripped.
    assert "$schema" not in describe(TOOLS[0])["input_schema"]  # type: ignore[index]


def test_tool_names_are_safe_for_every_provider() -> None:
    name = tool_name("crm", "find customer/by.email" + "x" * 80)
    assert name.startswith("mcp__crm__find_customer_by_email")
    assert len(name) <= 64


async def test_a_built_tool_runs_with_the_grant_and_reports_server_errors(
    server: FakeMcpServer,
) -> None:
    from tests.fake_mcp import TOOLS

    tools = {t.name: t for t in build_tools("crm", "CRM", [d for d in map(describe, TOOLS) if d])}
    find = tools["mcp__crm__find_customer"]
    assert find.side_effect is SideEffect.READ
    assert find.json_schema()["required"] == ["query"]

    ctx = ToolContext(
        owner_id=__import__("uuid").uuid4(), grants={"mcp:crm": Grant("", {"url": URL})}
    )
    found = await find().execute(ctx, {"query": "Asha"})
    assert found.ok and "Asha Rao" in found.data

    refused = await tools["mcp__crm__delete_contact"]().execute(ctx, {"id": "7"})
    assert not refused.ok and refused.error_class == "tool_error"
    assert "protected" in (refused.message or "")


async def test_a_dry_run_never_calls_a_tool_that_changes_things(server: FakeMcpServer) -> None:
    from tests.fake_mcp import TOOLS

    tools = {t.name: t for t in build_tools("crm", "CRM", [d for d in map(describe, TOOLS) if d])}
    ctx = ToolContext(
        owner_id=__import__("uuid").uuid4(),
        dry_run=True,
        grants={"mcp:crm": Grant("", {"url": URL})},
    )
    result = await tools["mcp__crm__update_deal_stage"]().execute(
        ctx, {"deal_id": "1", "stage": "won"}
    )

    assert result.ok and result.data["dry_run"] is True
    assert server.calls == []


async def test_without_the_server_connected_the_tool_says_so(server: FakeMcpServer) -> None:
    from tests.fake_mcp import TOOLS

    find = build_tools("crm", "CRM", [describe(TOOLS[0])])[0]  # type: ignore[list-item]
    result = await find().execute(ToolContext(owner_id=__import__("uuid").uuid4()), {"query": "x"})
    assert result.error_class == "not_connected"
