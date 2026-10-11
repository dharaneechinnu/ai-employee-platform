"""The tool contract.

A tool is a door we open for the model. The model never touches an
outside system directly: it asks us to run a named tool, we check
whether that is allowed, and we execute it with the customer's
credential attached.

That indirection is the strongest security property in the design. If
an employee has no `delete_repository` tool, deleting a repository is
impossible no matter what text an attacker plants in a GitHub issue.
Capability limits beat instruction-following.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError


class SideEffect(StrEnum):
    """What a tool changes in the real world.

    Phase 5's permission policy keys off this, which only works if
    every tool carries one. `Tool` has no default, so a tool missing
    this attribute fails at registration rather than shipping
    unlabelled.
    """

    READ = "read"  # looks only
    WRITE = "write"  # creates or changes something; usually reversible
    DESTRUCTIVE = "destructive"  # deletes or sends; cannot be undone


@dataclass(slots=True)
class ToolContext:
    """What a tool is given at call time.

    `credential` is resolved by the worker immediately before the call
    and is never placed in the model's context. There is nothing for a
    prompt-injection attack to extract, because the secret was never
    in the conversation.
    """

    org_id: uuid.UUID
    run_id: uuid.UUID | None = None
    credential: str | None = None
    config: dict[str, Any] | None = None
    dry_run: bool = False


@dataclass(slots=True)
class ToolResult:
    ok: bool
    data: Any = None
    error_class: str | None = None
    message: str | None = None

    @classmethod
    def success(cls, data: Any) -> ToolResult:
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error_class: str, message: str) -> ToolResult:
        return cls(ok=False, error_class=error_class, message=message)

    def as_text(self) -> str:
        """What the model sees.

        A failure is returned as a sentence rather than raised. The
        model can then read "that file does not exist" and try a
        different path, which is most of the difference between an
        agent that feels capable and one that feels broken.
        """
        if self.ok:
            if isinstance(self.data, str):
                return self.data
            import json

            return json.dumps(self.data, default=str)[:20000]
        return f"Tool failed ({self.error_class}): {self.message}"

    def summary(self) -> dict[str, Any]:
        return {"ok": self.ok, "error_class": self.error_class}


class Tool(ABC):
    name: ClassVar[str]
    pack: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]
    side_effect: ClassVar[SideEffect]  # no default, on purpose
    supports_dry_run: ClassVar[bool] = False
    timeout_s: ClassVar[float] = 30.0
    requires_connection: ClassVar[str | None] = None

    @abstractmethod
    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolResult: ...

    async def execute(self, ctx: ToolContext, raw_args: dict[str, Any]) -> ToolResult:
        """Validate arguments, then run.

        Bad arguments come back as a readable message rather than an
        exception, so the model can correct itself on the next step.
        """
        try:
            args = self.args_model.model_validate(raw_args)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            return ToolResult.failure("invalid_arguments", problems)

        return await self.run(ctx, args)

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        schema = cls.args_model.model_json_schema()
        schema.pop("title", None)
        return schema
