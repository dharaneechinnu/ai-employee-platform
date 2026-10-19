"""The tool catalogue.

Two rules are enforced at registration, not at call time, so a mistake
stops the process from starting rather than surfacing in production:

1. A tool must declare `side_effect`. Phase 5's permission policy keys
   off it, and a tool that slipped through unlabelled would be the one
   that emails four hundred customers.

2. A tool on the catastrophic blocklist cannot be registered at all.
"""

from __future__ import annotations

from app.agent.tools.base import SideEffect, Tool

# Actions nobody may enable, not even by changing their own policy.
# Deliberately tiny, and each entry carries its reason. A company that
# sets "delete repository" to automatic and loses a repository will
# contact us, not themselves, so the reputational cost lands here
# either way.
BLOCKED_ACTIONS: dict[str, str] = {
    "delete_repository": "Destroys all history. Usually unrecoverable.",
    "force_push": "Silently erases other people's work.",
    "email_all_contacts": "One mistake reaches thousands of real people.",
}


class ToolRegistryError(RuntimeError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, type[Tool]] = {}

    def register(self, tool: type[Tool]) -> type[Tool]:
        name = getattr(tool, "name", None)
        if not name:
            raise ToolRegistryError(f"{tool.__name__} must declare a name")

        if not isinstance(getattr(tool, "side_effect", None), SideEffect):
            raise ToolRegistryError(
                f"{tool.__name__} must declare side_effect "
                "(read, write or destructive). Phase 5's permission "
                "policy cannot gate an unlabelled tool."
            )

        if name in BLOCKED_ACTIONS:
            raise ToolRegistryError(
                f"'{name}' is on the catastrophic blocklist: {BLOCKED_ACTIONS[name]}"
            )

        if name in self._tools and self._tools[name] is not tool:
            raise ToolRegistryError(f"Two different tools both named '{name}'")

        self._tools[name] = tool
        return tool

    def get(self, name: str) -> type[Tool] | None:
        return self._tools.get(name)

    def all(self) -> list[type[Tool]]:
        return sorted(self._tools.values(), key=lambda t: (t.pack, t.name))

    def for_employee(
        self, enabled: list[str], extra: dict[str, type[Tool]] | None = None
    ) -> list[type[Tool]]:
        """Only what this employee is allowed.

        A tool absent from this list is not described to the model at
        all, so as far as the model is concerned it does not exist.
        `extra` holds the company's own tools (from MCP servers), which
        live outside the global catalogue.
        """
        extra = extra or {}
        found = [self._tools.get(n) or extra.get(n) for n in enabled]
        return [t for t in found if t is not None]

    def schemas(self, tools: list[type[Tool]]) -> list[dict[str, object]]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.json_schema()}
            for t in tools
        ]


registry = ToolRegistry()


def register(tool: type[Tool]) -> type[Tool]:
    """Decorator form."""
    return registry.register(tool)
