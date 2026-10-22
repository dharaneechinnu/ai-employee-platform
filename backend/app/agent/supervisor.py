"""Team mode as a LangGraph graph: route, work side by side, merge, review.

    router -> helpers (at the same time) -> lead -> [writer -> critic -> writer ...]

- The router makes one cheap model call that picks which helpers the
  request needs. If it cannot be read, or says no help is needed, the
  lead simply answers alone, as in a chat without a team.
- The helpers are the roster in `team.py`, started through the same
  `run_specialist` the `ask_specialist` tool uses, so they are read-only,
  follow the person's Permissions, and are shown and costed the same way.
- The lead is the ordinary assistant (`AgentLoop`). It receives what the
  helpers found, and it is the only step that may use write tools, so an
  approval pause still happens here and ends the graph like any pause.
- When a report was asked for, the writer drafts it and the critic checks
  it. A draft with problems goes back to the writer, at most
  `MAX_REVIEW_ROUNDS` times, and then goes out with the open problems
  listed rather than looping on.

Limits live here as constants, because a graph that loops or fans out is
how one question turns into a bill.
"""

from __future__ import annotations

import json
import operator
import re
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agent.loop import AgentLoop, RunOutcome
from app.agent.providers.base import LLMError, Message, Role
from app.agent.team import MAX_SPECIALIST_CALLS, ROLES, Team, run_specialist

MAX_REVIEW_ROUNDS = 2
# Helpers the router may start in parallel. The writer and critic belong to
# the report loop, so the router cannot pick them.
PARALLEL_ROLES = ("researcher", "analyst", "developer", "generalist")
# Past this many tokens spent by helpers and reviewers, no more are started.
TEAM_TOKEN_BUDGET = 150_000
MAX_FINDING_CHARS = 6000

ROUTER_PROMPT = """\
You decide which helpers a request needs. Helpers:
- researcher: finds and reads sources on the web or in the person's files
- analyst: works through numbers, data, logic or options
- developer: reads and explains code in a repository
- generalist: anything else that can be done on its own

Reply with JSON only, no other text:
{"helpers": [{"role": "<one of the above>", "task": "<a task that stands alone>"}],
 "report": <true or false>}

Rules:
- A simple question, chat or greeting needs no helpers: {"helpers": [], "report": false}.
- Pick only helpers whose work is independent, so they can run at the same time. At most 4.
- Write each task so it makes sense without the conversation.
- "report" is true only when the person asked for a report, document or write-up.
"""

REVIEW_SUFFIX = (
    "\n\nReply with APPROVED on the first line if this is good enough to send. Otherwise "
    "reply with CHANGES NEEDED on the first line, then a numbered list of the fixes, most "
    "important first."
)


@dataclass(slots=True)
class Finding:
    role: str
    ok: bool
    answer: str


class SupervisorState(TypedDict, total=False):
    request: str
    system_prompt: str
    history: list[Message] | None
    helpers: list[dict[str, str]]
    report: bool
    # Added to by every helper at the same time, so it appends rather than replaces.
    findings: Annotated[list[Finding], operator.add]
    outcome: RunOutcome
    draft: str
    critique: str
    approved: bool
    round: int
    stopped: bool


# ---------------------------------------------------------------- router


def parse_plan(text: str | None) -> tuple[list[dict[str, str]], bool]:
    """Read the router's reply. Anything unreadable means "no team"."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return [], False
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return [], False
    if not isinstance(data, dict):
        return [], False

    helpers: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in data.get("helpers") or []:
        if not isinstance(item, dict):
            continue
        role, task = item.get("role"), item.get("task")
        if role not in PARALLEL_ROLES or not isinstance(task, str) or not task.strip():
            continue
        key = (role, task.strip())
        if key in seen:
            continue
        seen.add(key)
        helpers.append({"role": role, "task": task.strip()[:6000]})
    return helpers[:MAX_SPECIALIST_CALLS], data.get("report") is True


# ----------------------------------------------------------------- lead


def lead_task(request: str, findings: list[Finding]) -> str:
    if not findings:
        return request
    parts = [request, "", "---", "Your team has already worked on this. What they found:"]
    for f in findings:
        label = ROLES[f.role].label
        if f.ok:
            parts += ["", f"[{label}]", f.answer[:MAX_FINDING_CHARS]]
        else:
            parts += [
                "",
                f"[{label}] could not finish this part. Cover it yourself or say it is missing.",
            ]
    parts += [
        "",
        "Answer the request using this. Check it before relying on it, and say what is "
        "uncertain or missing.",
    ]
    return "\n".join(parts)


def verdict(review: str) -> bool:
    first = next((ln.strip() for ln in review.splitlines() if ln.strip()), "")
    return first.upper().startswith("APPROVED")


# ----------------------------------------------------------------- graph


def build_supervisor(loop: AgentLoop, team: Team) -> Any:
    ctx = loop.tool_context

    def over_budget() -> bool:
        return team.prompt_tokens + team.output_tokens >= TEAM_TOKEN_BUDGET

    async def router(state: SupervisorState) -> SupervisorState:
        # A run resumed after an approval has already had its team work.
        if loop.resuming:
            return {"helpers": [], "report": False}
        try:
            reply = await team.provider.complete(
                messages=[
                    Message(role=Role.SYSTEM, content=ROUTER_PROMPT),
                    Message(role=Role.USER, content=state["request"]),
                ],
                model=team.model,
                tools=None,
                temperature=0.0,
                max_tokens=600,
            )
        except LLMError:
            return {"helpers": [], "report": False}
        team.prompt_tokens += reply.usage.prompt_tokens
        team.output_tokens += reply.usage.output_tokens
        helpers, report = parse_plan(reply.text)
        await team.emit("supervisor_plan", helpers=[h["role"] for h in helpers], report=report)
        return {"helpers": helpers, "report": report}

    def after_router(state: SupervisorState) -> list[Send] | str:
        helpers = state.get("helpers") or []
        if not helpers:
            return "lead"
        return [Send("helper", h) for h in helpers]

    async def helper(task: dict[str, str]) -> SupervisorState:
        result = await run_specialist(team, ctx, task["role"], task["task"])
        return {"findings": [Finding(task["role"], result.ok, result.answer)]}

    async def lead(state: SupervisorState) -> SupervisorState:
        outcome = await loop.run(
            system_prompt=state["system_prompt"],
            task=lead_task(state["request"], state.get("findings") or []),
            history=state.get("history"),
        )
        return {"outcome": outcome, "draft": outcome.output or "", "round": 0}

    def after_lead(state: SupervisorState) -> str:
        outcome = state["outcome"]
        if not outcome.completed or not state.get("report") or over_budget():
            return END
        return "writer"

    async def writer(state: SupervisorState) -> SupervisorState:
        task = f"Request: {state['request']}\n\nMaterial to turn into the report:\n{state['draft']}"
        if state.get("critique"):
            task += f"\n\nA reviewer found these problems. Fix them:\n{state['critique']}"
        result = await run_specialist(team, ctx, "writer", task)
        # A writer that failed leaves the lead's draft as the answer.
        # Only a finished writer's text counts: a failed one's "answer" is the error.
        draft = result.answer if result.ok and result.answer else state["draft"]
        return {"draft": draft, "stopped": not result.ok}

    async def critic(state: SupervisorState) -> SupervisorState:
        result = await run_specialist(
            team, ctx, "critic", f"Review this report:\n\n{state['draft']}{REVIEW_SUFFIX}"
        )
        rounds = state.get("round", 0) + 1
        if not result.ok:
            return {"approved": True, "round": rounds}
        await team.emit("review_round", round=rounds, approved=verdict(result.answer))
        return {
            "approved": verdict(result.answer),
            "critique": result.answer,
            "round": rounds,
        }

    def after_critic(state: SupervisorState) -> str:
        if state.get("approved") or state.get("round", 0) >= MAX_REVIEW_ROUNDS or over_budget():
            return "finish"
        return "writer"

    def after_writer(state: SupervisorState) -> str:
        return "finish" if state.get("stopped") else "critic"

    async def finish(state: SupervisorState) -> SupervisorState:
        outcome = state["outcome"]
        draft = state.get("draft") or outcome.output or ""
        if state.get("report") and not state.get("approved", True) and state.get("critique"):
            draft += (
                "\n\n---\nOpen review notes (not fixed after the review rounds):\n"
                + state["critique"]
            )
        outcome.output = draft
        return {"outcome": outcome}

    graph = StateGraph(SupervisorState)
    graph.add_node("router", router)
    graph.add_node("helper", helper)
    graph.add_node("lead", lead)
    graph.add_node("writer", writer)
    graph.add_node("critic", critic)
    graph.add_node("finish", finish)

    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", after_router, ["helper", "lead"])
    graph.add_edge("helper", "lead")
    graph.add_conditional_edges("lead", after_lead, ["writer", END])
    graph.add_conditional_edges("writer", after_writer, ["critic", "finish"])
    graph.add_conditional_edges("critic", after_critic, ["writer", "finish"])
    graph.add_edge("finish", END)
    return graph.compile()


async def run_supervised(
    loop: AgentLoop,
    team: Team,
    *,
    system_prompt: str,
    task: str,
    history: list[Message] | None = None,
) -> RunOutcome:
    final = await build_supervisor(loop, team).ainvoke(
        {
            "request": task,
            "system_prompt": system_prompt,
            "history": history,
            "findings": [],
        }
    )
    outcome: RunOutcome = final["outcome"]
    return outcome
