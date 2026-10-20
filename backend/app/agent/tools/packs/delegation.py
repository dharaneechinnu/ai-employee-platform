"""Delegation: one AI Employee asking another for help.

The supervisor pattern, kept deliberately small.

Chaining agents multiplies error rates rather than adding them. At the
80% single-agent success rate this platform gates on:

    1 agent   0.80         = 80%
    2 chained 0.80 x 0.80  = 64%
    3 chained 0.80^3       = 51%

Three levels is a coin flip. Worse, a mistake by the first agent
becomes the second's *input*, so the second builds confidently on
wrong information - much harder to spot than a crash.

Hence: depth 1, at most three specialists, and the manager is told to
check what comes back rather than trust it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import register
from app.core.observability import get_logger

log = get_logger(__name__)

MAX_DELEGATION_DEPTH = 1
MAX_SPECIALISTS_PER_RUN = 3


class DelegateArgs(BaseModel):
    specialist_name: str = Field(
        description="The name of the AI Employee to ask, exactly as it is configured"
    )
    task: str = Field(
        min_length=1,
        max_length=4000,
        description="What you want them to do, written so it stands alone",
    )


@register
class DelegateToSpecialist(Tool):
    name = "delegate_to_specialist"
    pack = "delegation"
    description = (
        "Ask another AI Employee in this company to do part of the work and "
        "return the result. Use it when the task needs expertise or tools you "
        "do not have. Always check what comes back before relying on it."
    )
    args_model = DelegateArgs
    # A write: the specialist may itself take write actions, and those
    # are gated by the same policy the manager is subject to.
    side_effect = SideEffect.WRITE
    timeout_s = 300.0

    async def run(self, ctx: ToolContext, args: DelegateArgs) -> ToolResult:  # type: ignore[override]
        config = ctx.config or {}
        session = config.get("_session")
        if session is None:
            return ToolResult.failure("unavailable", "Delegation is not available in this run.")

        depth: int = config.get("_depth", 0)
        if depth >= MAX_DELEGATION_DEPTH:
            # The specialist cannot delegate onward. Without this cap a
            # chain forms, error rates multiply, and cost is unbounded.
            return ToolResult.failure(
                "depth_limit",
                "You were asked to do this work yourself and cannot pass it on again. "
                "Complete what you can and report honestly on the rest.",
            )

        used: set[str] = config.get("_delegated_to", set())
        if len(used) >= MAX_SPECIALISTS_PER_RUN:
            return ToolResult.failure(
                "too_many_specialists",
                f"You have already asked {MAX_SPECIALISTS_PER_RUN} colleagues on this task. "
                "Finish with what you have.",
            )

        from app.db.models.ai_employee import AIEmployee, AIEmployeeVersion, EmployeeStatus

        specialist = await session.scalar(
            select(AIEmployee).where(
                AIEmployee.owner_id == ctx.owner_id,
                AIEmployee.name == args.specialist_name,
                AIEmployee.status.in_((EmployeeStatus.ACTIVE, EmployeeStatus.DRAFT)),
            )
        )
        if specialist is None:
            available = (
                await session.scalars(
                    select(AIEmployee.name).where(
                        AIEmployee.owner_id == ctx.owner_id,
                        AIEmployee.status == EmployeeStatus.ACTIVE,
                    )
                )
            ).all()
            return ToolResult.failure(
                "not_found",
                f"There is no active AI Employee called '{args.specialist_name}'. "
                f"Available: {', '.join(available) or 'none'}.",
            )

        if specialist.id == config.get("_employee_id"):
            return ToolResult.failure("self_delegation", "You cannot delegate a task to yourself.")

        version = await session.scalar(
            select(AIEmployeeVersion)
            .where(AIEmployeeVersion.employee_id == specialist.id)
            .order_by(AIEmployeeVersion.version_no.desc())
            .limit(1)
        )
        if version is None:
            return ToolResult.failure("not_configured", f"{specialist.name} has no configuration.")

        result = await _run_specialist(
            ctx=ctx,
            session=session,
            specialist=specialist,
            version=version,
            task=args.task,
            depth=depth + 1,
            already_used=used,
        )
        used.add(args.specialist_name)
        config["_delegated_to"] = used
        return result


async def _run_specialist(
    *,
    ctx: ToolContext,
    session: object,
    specialist: object,
    version: object,
    task: str,
    depth: int,
    already_used: set[str],
) -> ToolResult:
    """Run a nested agent loop for the specialist.

    It gets its own budget and its own tool allowlist, so a manager
    cannot borrow capabilities it was not granted by delegating to
    someone who has them... except deliberately, which is the point of
    delegation. What it cannot do is exceed the policy: the specialist
    is checked against the same company policy as everyone else.
    """
    from app.agent.loop import AgentLoop, Budget
    from app.agent.providers import build_provider
    from app.agent.providers.fallback import FallbackProvider, Option
    from app.agent.tools.registry import registry
    from app.schemas.ai_employee import EmployeeConfig
    from app.services.employee_service import build_system_prompt
    from app.services.policy_service import PolicyService
    from app.services.provider_service import ProviderService

    config = EmployeeConfig.model_validate(version.config)  # type: ignore[attr-defined]
    providers = ProviderService(session, ctx.owner_id)  # type: ignore[arg-type]

    try:
        # With Automatic, the specialist's own preference picks the best
        # of the person's AIs for this piece of work, with fallbacks.
        options = []
        for choice in await providers.route(config.model, text=task, preference=config.routing):
            options.append(
                Option(
                    provider=build_provider(
                        choice.provider_key,
                        await providers.resolve_api_key(choice.provider_key),
                        base_url=await providers.resolve_base_url(choice.provider_key),
                    ),
                    provider_key=choice.provider_key,
                    model=choice.model,
                )
            )
    except Exception:  # noqa: BLE001 - reported to the manager, not raised
        return ToolResult.failure(
            "not_connected",
            f"{specialist.name} cannot run: no AI key is connected for its model.",  # type: ignore[attr-defined]
        )

    nested_context = ToolContext(
        owner_id=ctx.owner_id,
        run_id=ctx.run_id,
        dry_run=ctx.dry_run,
        # The specialist works for the same company, so it uses the
        # same connected apps. Its own tool allowlist still decides
        # which of them it can reach.
        grants=ctx.grants,
        config={
            **(ctx.config or {}),
            "_employee_id": specialist.id,  # type: ignore[attr-defined]
            "_depth": depth,
            "_delegated_to": already_used,
        },
    )

    resolver = await PolicyService(session, ctx.owner_id).resolver()  # type: ignore[arg-type]
    loop = AgentLoop(
        provider=FallbackProvider(options),
        model=options[0].model,
        tools=registry.for_employee(config.enabled_tools, extra=resolver.extra_tools),
        tool_context=nested_context,
        # A smaller budget than the manager: a specialist is doing one
        # part of the job, and a nested runaway is harder to notice.
        budget=Budget(max_steps=min(config.max_steps, 8)),
        temperature=config.temperature,
        # The company's permission rules apply to specialists too, so a
        # tool set to "Blocked" stays blocked however the work arrives.
        check_policy=specialist_policy(resolver),
    )

    outcome = await loop.run(
        system_prompt=build_system_prompt(
            config,
            name=specialist.name,  # type: ignore[attr-defined]
            job_title=specialist.job_title,  # type: ignore[attr-defined]
        ),
        task=task,
    )

    log.info(
        "delegation_completed",
        specialist=specialist.name,  # type: ignore[attr-defined]
        depth=depth,
        stop_cause=outcome.stop_cause,
        steps=outcome.steps,
    )

    if not outcome.completed:
        return ToolResult.failure(
            "specialist_failed",
            f"{specialist.name} could not finish ({outcome.stop_cause}). "  # type: ignore[attr-defined]
            "Decide whether to continue without that part.",
        )

    return ToolResult.success(
        {
            "specialist": specialist.name,  # type: ignore[attr-defined]
            "answer": outcome.output,
            "steps_taken": outcome.steps,
        }
    )


def specialist_policy(resolver: Any) -> Callable[[str], tuple[str, str]]:
    """The permission check for a specialist's own tool calls.

    "Always allow" and "Blocked" apply exactly as for any AI Employee.
    "Ask me first" becomes a refusal with a reason: a specialist runs
    inside its manager's step and cannot pause for a person, so the
    manager is told to take that step itself, where the normal approval
    happens. Without this, delegating was a way round every rule.
    """

    def check(tool_name: str) -> tuple[str, str]:
        decision = resolver.evaluate(tool_name)
        setting = decision.setting.value
        if setting == "ask":
            return (
                "blocked",
                "it needs a person's approval, which a specialist cannot wait for; "
                "hand this step back to your manager to do",
            )
        return setting, decision.reason

    return check


def new_delegation_id() -> uuid.UUID:
    return uuid.uuid4()
