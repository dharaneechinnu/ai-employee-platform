"""Agent orchestration for the personal assistant: a lead and specialists.

The lead (the assistant the person talks to) plans, hands independent
parts to specialists through one tool, `ask_specialist`, and combines
what comes back. Asking several specialists in one step runs them at
the same time, because the loop already runs independent tool calls
in parallel: fan out, then fan in.

The limits are the point, because chained agents multiply each
other's errors:

- Depth 1. A specialist has no `ask_specialist` tool, so it cannot
  start a chain. Chained agents multiply each other's error rates.
- At most `MAX_SPECIALIST_CALLS` per turn, each with a small step
  budget, so one question cannot fan out into a bill.
- Specialists obey the person's permissions. "Ask me first" becomes a
  refusal, because a specialist works inside the lead's step and cannot
  pause for a person; the lead does that step itself, where approval
  happens normally.
- Specialists see only the task text they were given, never the
  conversation, and never any secret.

Every specialist's start, steps and finish are written to the run's
event log, so the person can watch the team work live and replay it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult

MAX_SPECIALIST_CALLS = 6
SPECIALIST_MAX_STEPS = 6
SPECIALIST_SECONDS = 180.0

# Tools that share the run's database session. Parallel specialists
# must not use one session at the same time, so these stay with the lead.
_LEAD_ONLY_PACKS = {"memory", "team"}

RoleKey = Literal["researcher", "analyst", "writer", "critic", "developer", "generalist"]


@dataclass(frozen=True, slots=True)
class SpecialistRole:
    """One agent of the team. `tools` names the only tools it is offered
    and `packs` adds whole packs; with neither, it gets every read-only
    tool the person has. Either way it is cut down to the person's
    Permissions, and to read-only (see `specialist_tools`)."""

    key: str
    label: str
    instructions: str
    uses_tools: bool
    tools: tuple[str, ...] | None = None
    packs: tuple[str, ...] = ()


ROLES: dict[str, SpecialistRole] = {
    "researcher": SpecialistRole(
        key="researcher",
        label="Researcher",
        instructions=(
            "You are a researcher. Find and read what is needed to answer the task, using "
            "your tools when they help. Report facts with where they came from, and mark "
            "anything uncertain. Do not pad: a short, sourced report beats a long one."
        ),
        uses_tools=True,
    ),
    "analyst": SpecialistRole(
        key="analyst",
        label="Analyst",
        instructions=(
            "You are an analyst. Work through the numbers, logic or options in the task "
            "step by step. Show the reasoning that matters, state assumptions, and end "
            "with a clear conclusion or recommendation. Use the calculator for every "
            "sum, percentage or average instead of working it out in your head."
        ),
        uses_tools=True,
        tools=(
            "calculator",
            "text_tools",
            "current_time",
            "sheets_read",
            "google_drive_search",
            "google_drive_read",
        ),
    ),
    "writer": SpecialistRole(
        key="writer",
        label="Writer",
        instructions=(
            "You are a writer. Turn the material in the task into clear, well-structured "
            "text for the stated reader. Keep every fact you were given; add none. When "
            "the task asks for a finished report, build it with report_write, with the "
            "sources you were given listed."
        ),
        uses_tools=True,
        tools=("report_write", "text_tools", "current_time"),
    ),
    "critic": SpecialistRole(
        key="critic",
        label="Critic",
        instructions=(
            "You are a critic. Check the draft or claim in the task for factual errors, "
            "gaps, weak reasoning and unclear wording. List the problems in order of "
            "importance with a fix for each. If it is good, say so briefly. Check figures "
            "with the calculator and quoted facts against their source when you can."
        ),
        uses_tools=True,
        tools=("text_tools", "calculator", "get_webpage", "web_search", "current_time"),
    ),
    "developer": SpecialistRole(
        key="developer",
        label="Developer",
        instructions=(
            "You are a senior software engineer. Read the relevant code before answering "
            "and say which files you read. Lead with the answer or the fix, then why. "
            "Show code in fenced blocks with the language, keep changes minimal, and "
            "point out edge cases, tests to add and security issues. You can read code "
            "but not change it or run it: say what you could not verify."
        ),
        uses_tools=True,
        tools=("text_tools", "calculator", "get_webpage", "current_time"),
        packs=("github",),
    ),
    "generalist": SpecialistRole(
        key="generalist",
        label="General",
        instructions=(
            "You are a capable all-round assistant. Do the task as written, using your "
            "tools when they help, and answer plainly. If it clearly needs a specialist's "
            "depth, say what is missing instead of guessing."
        ),
        uses_tools=True,
    ),
}

Emit = Callable[..., Awaitable[None]]
PolicyCheck = Callable[[str], tuple[str, str]]


@dataclass(slots=True)
class Team:
    """What `ask_specialist` needs from the run that hosts it. Kept in
    the tool context, never shown to a model."""

    provider: Any
    model: str
    tools: list[type[Tool]]
    check_policy: PolicyCheck
    emit: Emit
    # Role -> (provider, model, "provider:model"). None: every
    # specialist uses the lead's AI.
    provider_for: Callable[[str], tuple[Any, str, str]] | None = None
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    roles_used: list[str] = field(default_factory=list)


def specialist_tools(tools: list[type[Tool]], role: SpecialistRole) -> list[type[Tool]]:
    """A specialist may read, never change: a lead's write needs the
    person's eye, and the specialist cannot stop to ask. On top of that,
    each role sees only its own tools, so the reviewer cannot wander into
    the person's mail and the report writer cannot browse the web."""
    if not role.uses_tools:
        return []
    allowed = [
        t for t in tools if t.pack not in _LEAD_ONLY_PACKS and t.side_effect is SideEffect.READ
    ]
    if role.tools is None and not role.packs:
        return allowed
    return [t for t in allowed if t.name in (role.tools or ()) or t.pack in role.packs]


@dataclass(slots=True)
class SpecialistResult:
    role: SpecialistRole
    ok: bool
    answer: str
    stop_cause: str


async def run_specialist(
    team: Team, ctx: ToolContext, role_key: str, task: str
) -> SpecialistResult:
    """Run one specialist to the end and report it to the run's event log.

    Shared by the `ask_specialist` tool and the supervisor graph, so a
    specialist behaves, and is shown and costed, the same way however it
    was started. The caller checks the per-turn limit.
    """
    from app.agent.loop import AgentEvent, AgentLoop, Budget

    role = ROLES[role_key]
    team.calls += 1
    sid = f"s{team.calls}"
    team.roles_used.append(role.key)
    provider, model, label = (
        team.provider_for(role.key) if team.provider_for else (team.provider, team.model, None)
    )
    await team.emit("specialist_started", id=sid, role=role.key, task=task[:400], model=label)

    async def forward(event: AgentEvent) -> None:
        if event.type in ("tool_call", "tool_result", "tool_blocked", "llm_call"):
            await team.emit(
                "specialist_step",
                id=sid,
                role=role.key,
                kind=event.type,
                tool=event.payload.get("tool"),
                ok=event.payload.get("ok"),
            )

    # The specialist's own context: the lead's connected apps, but
    # not the team itself or the lead's database session.
    config = {k: v for k, v in (ctx.config or {}).items() if k not in ("_team", "_session")}
    loop = AgentLoop(
        provider=provider,
        model=model,
        tools=specialist_tools(team.tools, role),
        tool_context=replace(ctx, config=config),
        budget=Budget(max_steps=SPECIALIST_MAX_STEPS, max_seconds=SPECIALIST_SECONDS),
        temperature=0.3,
        on_event=forward,
        check_policy=team.check_policy,
    )
    outcome = await loop.run(system_prompt=role.instructions, task=task)
    team.prompt_tokens += outcome.prompt_tokens
    team.output_tokens += outcome.output_tokens

    await team.emit(
        "specialist_finished",
        id=sid,
        role=role.key,
        ok=outcome.completed,
        steps=outcome.steps,
        prompt_tokens=outcome.prompt_tokens,
        output_tokens=outcome.output_tokens,
        cost_usd=_cost(label, outcome.prompt_tokens, outcome.output_tokens),
    )
    return SpecialistResult(
        role=role,
        ok=outcome.completed,
        answer=outcome.output or "",
        stop_cause=outcome.stop_cause,
    )


class AskSpecialistArgs(BaseModel):
    role: RoleKey = Field(
        description="researcher, analyst, writer, critic, developer or generalist"
    )
    task: str = Field(
        min_length=1,
        max_length=6000,
        description="The task, written so it stands alone: the specialist cannot see the chat",
    )


class AskSpecialist(Tool):
    """Not in the global registry: it exists only in a conversation with
    team mode on, where the run supplies the `Team` it needs."""

    name = "ask_specialist"
    pack = "team"
    description = (
        "Hand an independent part of the work to a specialist (researcher, analyst, "
        "writer, critic, developer or generalist) and get their answer back. Ask several in "
        "the same step to "
        "run them at the same time. Check what comes back before using it."
    )
    args_model = AskSpecialistArgs
    # Specialists can only read (see `specialist_tools`), so asking one
    # changes nothing in the world.
    side_effect = SideEffect.READ
    timeout_s = SPECIALIST_SECONDS + 20

    async def run(self, ctx: ToolContext, args: AskSpecialistArgs) -> ToolResult:  # type: ignore[override]
        team: Team | None = (ctx.config or {}).get("_team")
        if team is None:
            return ToolResult.failure("unavailable", "Specialists are not available here.")
        if team.calls >= MAX_SPECIALIST_CALLS:
            return ToolResult.failure(
                "team_limit",
                f"You have asked specialists {MAX_SPECIALIST_CALLS} times this turn. "
                "Finish with what you have.",
            )

        result = await run_specialist(team, ctx, args.role, args.task)
        if not result.ok:
            return ToolResult.failure(
                "specialist_failed",
                f"The {result.role.label.lower()} could not finish ({result.stop_cause}). "
                "Carry on without that part, or do it yourself.",
            )
        return ToolResult.success({"specialist": result.role.label, "answer": result.answer})


def _cost(label: str | None, prompt_tokens: int, output_tokens: int) -> float:
    """Estimated cost of one specialist, for the flow view. `label` is
    "provider:model"; without one the lead's cost line covers it."""
    if not label or ":" not in label:
        return 0.0
    from app.services.task_service import estimate_cost

    provider_key, model = label.split(":", 1)
    return float(estimate_cost(provider_key, model, prompt_tokens, output_tokens))


def specialist_policy(resolver: Any) -> Callable[[str], tuple[str, str]]:
    """The permission check for a specialist's own tool calls.

    "Always allow" and "Blocked" apply exactly as they do for the lead.
    "Ask me first" becomes a refusal with a reason: a specialist runs
    inside the lead's step and cannot pause for a person, so the lead
    is told to take that step itself, where the normal approval
    happens. Without this, handing work to a specialist was a way round
    every rule.
    """

    def check(tool_name: str) -> tuple[str, str]:
        decision = resolver.evaluate(tool_name)
        setting = decision.setting.value
        if setting == "ask":
            return (
                "blocked",
                "it needs a person's approval, which a specialist cannot wait for; "
                "hand this step back to the lead to do",
            )
        return setting, decision.reason

    return check
