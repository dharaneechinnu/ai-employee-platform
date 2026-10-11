"""Registry rules, enforced at registration rather than at call time."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import BLOCKED_ACTIONS, ToolRegistry, ToolRegistryError, registry


class NoArgs(BaseModel):
    pass


def _tool(name: str, side_effect: SideEffect | None = SideEffect.READ) -> type[Tool]:
    attrs: dict[str, object] = {
        "name": name,
        "pack": "test",
        "description": "test tool",
        "args_model": NoArgs,
        "run": lambda self, ctx, args: ToolResult.success("ok"),
    }
    if side_effect is not None:
        attrs["side_effect"] = side_effect
    return type(f"Tool_{name}", (Tool,), attrs)  # type: ignore[return-value]


def test_a_tool_without_a_side_effect_label_cannot_be_registered() -> None:
    """Phase 5's permission policy keys off this label. A tool that
    slipped through unlabelled would be the one that emails four
    hundred customers, so this fails at import rather than at runtime."""
    with pytest.raises(ToolRegistryError, match="side_effect"):
        ToolRegistry().register(_tool("unlabelled", side_effect=None))


def test_a_catastrophic_action_cannot_be_registered() -> None:
    with pytest.raises(ToolRegistryError, match="blocklist"):
        ToolRegistry().register(_tool("delete_repository"))


def test_two_different_tools_cannot_share_a_name() -> None:
    reg = ToolRegistry()
    reg.register(_tool("duplicate"))
    with pytest.raises(ToolRegistryError, match="both named"):
        reg.register(_tool("duplicate"))


def test_for_employee_returns_only_the_allowed_tools() -> None:
    reg = ToolRegistry()
    reg.register(_tool("allowed"))
    reg.register(_tool("not_allowed"))

    assert [t.name for t in reg.for_employee(["allowed"])] == ["allowed"]


def test_an_unknown_tool_name_is_ignored_rather_than_raising() -> None:
    """Configuration can outlive a tool that was removed. Dropping it
    quietly is better than breaking every run for that employee."""
    reg = ToolRegistry()
    reg.register(_tool("real"))

    assert [t.name for t in reg.for_employee(["real", "deleted_last_year"])] == ["real"]


def test_the_starter_pack_is_registered() -> None:
    assert registry.get("get_webpage") is not None


def test_every_registered_tool_carries_a_label() -> None:
    for tool in registry.all():
        assert isinstance(tool.side_effect, SideEffect), f"{tool.name} has no side_effect"


def test_the_blocklist_is_documented() -> None:
    """Each entry needs a reason, so none is ever added silently."""
    assert all(reason.strip() for reason in BLOCKED_ACTIONS.values())


_ = ToolContext  # used by tool implementations
