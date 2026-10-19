"""Memory tools.

The model decides when memory is relevant, by calling `recall`. We do
not guess for it by stuffing history into every request: that costs
money, fills the context window, and buries the one useful fact in
noise, which makes answers worse rather than better.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import register


class RecallArgs(BaseModel):
    query: str = Field(description="What you want to remember, in plain words")
    limit: int = Field(default=5, ge=1, le=20)


@register
class Recall(Tool):
    name = "recall"
    pack = "memory"
    description = (
        "Search what this company has told you before: facts, corrections and "
        "lessons from past tasks. Use it before guessing or asking the user "
        "something they may already have answered."
    )
    args_model = RecallArgs
    side_effect = SideEffect.READ
    timeout_s = 20.0

    async def run(self, ctx: ToolContext, args: RecallArgs) -> ToolResult:  # type: ignore[override]
        session = (ctx.config or {}).get("_session")
        if session is None:
            return ToolResult.failure("unavailable", "Memory is not available in this run.")

        from app.core.errors import ConflictError
        from app.services.memory_service import MemoryService

        service = MemoryService(session, ctx.owner_id)
        try:
            hits = await service.recall(
                args.query,
                employee_id=(ctx.config or {}).get("_employee_id"),
                limit=args.limit,
            )
        except ConflictError as exc:
            # Mixed embedding models. Say so plainly rather than return
            # results that look right and are not.
            return ToolResult.failure("needs_reembedding", exc.message)

        if not hits:
            return ToolResult.success({"found": 0, "memories": []})

        return ToolResult.success(
            {
                "found": len(hits),
                "memories": [
                    {
                        "content": h.memory.content,
                        "kind": str(h.memory.kind),
                        "matched_by": h.matched_by,
                    }
                    for h in hits
                ],
            }
        )


class RememberArgs(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=4000,
        description="One fact or correction, written so it makes sense on its own later",
    )
    company_wide: bool = Field(
        default=False,
        description="True if every AI Employee here should know it, false if only you should",
    )


@register
class Remember(Tool):
    name = "remember"
    pack = "memory"
    description = (
        "Save something worth knowing next time: a correction you were given, "
        "a convention this company follows, or a lesson from this task."
    )
    args_model = RememberArgs
    # A write rather than a read: it changes what every future run sees.
    side_effect = SideEffect.WRITE
    timeout_s = 20.0

    async def run(self, ctx: ToolContext, args: RememberArgs) -> ToolResult:  # type: ignore[override]
        session = (ctx.config or {}).get("_session")
        if session is None:
            return ToolResult.failure("unavailable", "Memory is not available in this run.")

        from app.db.models.memory import MemoryKind, MemoryScope
        from app.services.memory_service import MemoryService

        employee_id = (ctx.config or {}).get("_employee_id")
        scope = (
            MemoryScope.ORG if args.company_wide or employee_id is None else MemoryScope.EMPLOYEE
        )

        memory = await MemoryService(session, ctx.owner_id).remember(
            content=args.content,
            kind=MemoryKind.FACT,
            scope=scope,
            employee_id=employee_id,
            meta={"run_id": str(ctx.run_id) if ctx.run_id else None},
        )
        return ToolResult.success({"saved": True, "id": str(memory.id), "scope": str(scope)})
