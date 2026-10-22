"""Step 4b: the supervisor graph.

A fake AI answers according to who is asking (the router, the lead, or a
helper, told apart by the system prompt), so each test scripts a whole
team conversation and checks what the graph did with it.
"""

import asyncio
import uuid
from typing import Any

import pytest

from app.agent.loop import AgentLoop, Budget
from app.agent.providers.base import (
    LLMError,
    LLMProvider,
    LLMReply,
    Message,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from app.agent.supervisor import (
    MAX_REVIEW_ROUNDS,
    ROUTER_PROMPT,
    TEAM_TOKEN_BUDGET,
    Finding,
    lead_task,
    parse_plan,
    run_supervised,
    verdict,
)
from app.agent.team import MAX_SPECIALIST_CALLS, ROLES, Team
from app.agent.tools.base import ToolContext
from app.agent.tools.packs.calculator import Calculator
from app.agent.tools.packs.report import ReportWrite
from app.agent.tools.packs.text import TextTools

LEAD = "LEAD-PROMPT"


def reply(text: str | None = None, calls: list[ToolCall] | None = None) -> LLMReply:
    return LLMReply(
        message=Message(role=Role.ASSISTANT, content=text, tool_calls=calls or []),
        stop_reason=StopReason.TOOL_USE if calls else StopReason.END_TURN,
        usage=Usage(10, 5),
        model="m",
    )


class Cast(LLMProvider):
    """Answers by who is asking. `script[who]` is a list of replies, used in order
    (the last repeats)."""

    provider_key = "cast"

    def __init__(self, script: dict[str, list[Any]]) -> None:
        super().__init__(api_key="x")
        self.script = script
        self.seen: dict[str, list[list[Message]]] = {}
        self.index: dict[str, int] = {}
        self.gate: dict[str, asyncio.Event] = {}

    def who(self, messages: list[Message]) -> str:
        system = messages[0].content or ""
        if system == ROUTER_PROMPT:
            return "router"
        if system == LEAD:
            return "lead"
        for key, role in ROLES.items():
            if system == role.instructions:
                return key
        return "unknown"

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        messages: list[Message] = kwargs["messages"]
        who = self.who(messages)
        self.seen.setdefault(who, []).append(list(messages))
        n = self.index.get(who, 0)
        self.index[who] = n + 1
        item = self.script[who][min(n, len(self.script[who]) - 1)]
        if callable(item):
            item = await item(self)
        if isinstance(item, Exception):
            raise item
        return item

    async def check(self, model: str) -> None:
        return None


def make(
    provider: Cast, *, tools: list[Any] | None = None, **loop_kwargs: Any
) -> tuple[AgentLoop, Team, list[tuple[str, dict]]]:
    events: list[tuple[str, dict]] = []

    async def emit(type_: str, **payload: Any) -> None:
        events.append((type_, payload))

    ctx = ToolContext(owner_id=uuid.uuid4())
    team = Team(
        provider=provider,
        model="m",
        tools=[Calculator, TextTools, ReportWrite],
        check_policy=lambda name: ("auto", ""),
        emit=emit,
    )
    loop = AgentLoop(
        provider=provider,
        model="m",
        tools=tools or [],
        tool_context=ctx,
        budget=Budget(max_steps=6),
        **loop_kwargs,
    )
    return loop, team, events


def plan(*helpers: tuple[str, str], report: bool = False) -> LLMReply:
    import json

    return reply(
        json.dumps({"helpers": [{"role": r, "task": t} for r, t in helpers], "report": report})
    )


async def go(loop: AgentLoop, team: Team, request: str = "do the thing"):
    return await run_supervised(loop, team, system_prompt=LEAD, task=request)


# ------------------------------------------------------------ reading the plan


def test_a_good_plan_is_read() -> None:
    helpers, report = parse_plan(
        'Sure! {"helpers": [{"role": "researcher", "task": "Find X"},'
        ' {"role": "analyst", "task": "Work out Y"}], "report": true}'
    )
    assert [h["role"] for h in helpers] == ["researcher", "analyst"]
    assert report is True


@pytest.mark.parametrize(
    "text",
    [None, "", "no json here", "{broken", "[]", '{"helpers": "researcher"}', '{"helpers": [1]}'],
)
def test_an_unreadable_plan_means_no_team(text: str | None) -> None:
    assert parse_plan(text) == ([], False)


def test_the_router_cannot_pick_the_writer_or_critic_or_invent_roles() -> None:
    helpers, _ = parse_plan(
        '{"helpers": [{"role": "writer", "task": "a"}, {"role": "critic", "task": "b"},'
        ' {"role": "wizard", "task": "c"}, {"role": "researcher", "task": "  "},'
        ' {"role": "analyst", "task": "ok"}]}'
    )
    assert helpers == [{"role": "analyst", "task": "ok"}]


def test_the_plan_is_capped_and_deduplicated() -> None:
    many = ",".join(f'{{"role": "researcher", "task": "t{i}"}}' for i in range(20))
    helpers, _ = parse_plan('{"helpers": [' + many + "]}")
    assert len(helpers) == MAX_SPECIALIST_CALLS
    twice, _ = parse_plan(
        '{"helpers": [{"role": "analyst", "task": "same"}, {"role": "analyst", "task": "same"}]}'
    )
    assert len(twice) == 1


def test_the_verdict_reads_the_first_line() -> None:
    assert verdict("APPROVED\nnice")
    assert verdict("\n  approved - fine")
    assert not verdict("CHANGES NEEDED\n1. fix")
    assert not verdict("Looks good, APPROVED")  # not on the first line


def test_the_lead_is_told_what_failed() -> None:
    text = lead_task("Q", [Finding("researcher", True, "facts"), Finding("analyst", False, "")])
    assert "[Researcher]\nfacts" in text
    assert "[Analyst] could not finish" in text
    assert lead_task("Q", []) == "Q"


# -------------------------------------------------------------------- the graph


async def test_no_helpers_means_the_lead_answers_alone() -> None:
    provider = Cast({"router": [plan()], "lead": [reply("Hello!")]})
    loop, team, _ = make(provider)
    outcome = await go(loop, team, "hi")

    assert outcome.completed and outcome.output == "Hello!"
    assert team.calls == 0
    assert "researcher" not in provider.seen
    # The lead saw the plain request, not a findings block.
    assert provider.seen["lead"][0][-1].content == "hi"


async def test_an_unreadable_router_reply_falls_back_to_the_lead() -> None:
    provider = Cast({"router": [reply("I think you need a team!")], "lead": [reply("Done.")]})
    loop, team, _ = make(provider)
    outcome = await go(loop, team)
    assert outcome.output == "Done." and team.calls == 0


async def test_a_router_outage_falls_back_to_the_lead() -> None:
    provider = Cast({"router": [LLMError("down")], "lead": [reply("Done.")]})
    loop, team, _ = make(provider)
    outcome = await go(loop, team)
    assert outcome.output == "Done."


async def test_independent_helpers_run_at_the_same_time_and_the_lead_gets_both() -> None:
    async def researcher(p: Cast) -> LLMReply:
        # Waits for the analyst to start. If helpers ran one after another
        # this would never be released and the test would time out.
        p.gate["analyst_started"] = p.gate.get("analyst_started") or asyncio.Event()
        await asyncio.wait_for(p.gate["analyst_started"].wait(), 5)
        return reply("Facts from the web")

    async def analyst(p: Cast) -> LLMReply:
        p.gate["analyst_started"] = p.gate.get("analyst_started") or asyncio.Event()
        p.gate["analyst_started"].set()
        return reply("The numbers add up")

    provider = Cast(
        {
            "router": [plan(("researcher", "find"), ("analyst", "compute"))],
            "researcher": [researcher],
            "analyst": [analyst],
            "lead": [reply("Combined answer")],
        }
    )
    loop, team, events = make(provider)
    outcome = await go(loop, team)

    assert outcome.output == "Combined answer"
    assert team.calls == 2
    assert sorted(team.roles_used) == ["analyst", "researcher"]
    lead_saw = provider.seen["lead"][0][-1].content or ""
    assert "Facts from the web" in lead_saw and "The numbers add up" in lead_saw
    kinds = [e[0] for e in events]
    assert kinds.count("specialist_started") == 2
    assert kinds.count("specialist_finished") == 2
    assert "supervisor_plan" in kinds


async def test_a_failing_helper_does_not_sink_the_run() -> None:
    provider = Cast(
        {
            "router": [plan(("researcher", "find"), ("analyst", "compute"))],
            "researcher": [LLMError("rate limited")],
            "analyst": [reply("Numbers")],
            "lead": [reply("Best effort")],
        }
    )
    loop, team, _ = make(provider)
    outcome = await go(loop, team)

    assert outcome.completed and outcome.output == "Best effort"
    lead_saw = provider.seen["lead"][0][-1].content or ""
    assert "[Researcher] could not finish" in lead_saw
    assert "Numbers" in lead_saw


async def test_helpers_and_the_router_are_counted_in_the_team_tokens() -> None:
    provider = Cast(
        {
            "router": [plan(("analyst", "compute"))],
            "analyst": [reply("n")],
            "lead": [reply("ok")],
        }
    )
    loop, team, _ = make(provider)
    await go(loop, team)
    # Router call (10+5) plus the analyst (10+5).
    assert (team.prompt_tokens, team.output_tokens) == (20, 10)


# ------------------------------------------------------------ the review loop


async def test_a_report_is_reviewed_and_sent_back_once_then_approved() -> None:
    provider = Cast(
        {
            "router": [plan(("researcher", "find"), report=True)],
            "researcher": [reply("facts")],
            "lead": [reply("rough notes")],
            "writer": [reply("Draft 1"), reply("Draft 2")],
            "critic": [reply("CHANGES NEEDED\n1. cite a source"), reply("APPROVED")],
        }
    )
    loop, team, events = make(provider)
    outcome = await go(loop, team, "write me a report")

    assert outcome.output == "Draft 2"
    assert team.roles_used.count("writer") == 2
    assert team.roles_used.count("critic") == 2
    rounds = [p for t, p in events if t == "review_round"]
    assert [r["approved"] for r in rounds] == [False, True]
    # The second draft was written with the critic's fixes in hand.
    second_task = provider.seen["writer"][1][-1].content or ""
    assert "cite a source" in second_task
    assert "rough notes" in provider.seen["writer"][0][-1].content


async def test_the_review_loop_stops_after_the_round_limit_and_lists_what_is_open() -> None:
    provider = Cast(
        {
            "router": [plan(report=True)],
            "lead": [reply("notes")],
            "writer": [reply("Draft")],
            "critic": [reply("CHANGES NEEDED\n1. still wrong")],
        }
    )
    loop, team, _ = make(provider)
    outcome = await go(loop, team)

    assert team.roles_used.count("critic") == MAX_REVIEW_ROUNDS
    assert team.roles_used.count("writer") == MAX_REVIEW_ROUNDS
    assert outcome.output is not None
    assert outcome.output.startswith("Draft")
    assert "Open review notes" in outcome.output and "still wrong" in outcome.output


async def test_an_approved_first_draft_is_sent_unchanged() -> None:
    provider = Cast(
        {
            "router": [plan(report=True)],
            "lead": [reply("notes")],
            "writer": [reply("Great report")],
            "critic": [reply("APPROVED")],
        }
    )
    loop, team, _ = make(provider)
    outcome = await go(loop, team)
    assert outcome.output == "Great report"
    assert team.roles_used.count("writer") == 1


async def test_no_report_means_no_writer_or_critic() -> None:
    provider = Cast(
        {"router": [plan(("analyst", "x"))], "analyst": [reply("a")], "lead": [reply("L")]}
    )
    loop, team, _ = make(provider)
    await go(loop, team)
    assert "writer" not in team.roles_used and "critic" not in team.roles_used


async def test_a_failed_writer_leaves_the_leads_answer() -> None:
    provider = Cast(
        {
            "router": [plan(report=True)],
            "lead": [reply("the lead's answer")],
            "writer": [LLMError("down")],
        }
    )
    loop, team, _ = make(provider)
    outcome = await go(loop, team)
    assert outcome.output == "the lead's answer"
    assert "critic" not in team.roles_used


async def test_a_failed_critic_does_not_block_the_report() -> None:
    provider = Cast(
        {
            "router": [plan(report=True)],
            "lead": [reply("notes")],
            "writer": [reply("Draft")],
            "critic": [LLMError("down")],
        }
    )
    loop, team, _ = make(provider)
    outcome = await go(loop, team)
    assert outcome.output == "Draft"


async def test_helpers_stop_when_the_team_has_spent_its_budget() -> None:
    provider = Cast({"router": [plan(report=True)], "lead": [reply("notes")]})
    loop, team, _ = make(provider)
    team.prompt_tokens = TEAM_TOKEN_BUDGET  # already spent
    outcome = await go(loop, team)
    assert outcome.output == "notes"
    assert "writer" not in team.roles_used


# ------------------------------------------------------- pauses and resuming


async def test_a_paused_lead_ends_the_graph_before_any_review() -> None:
    ask = reply(calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "1+1"})])
    provider = Cast({"router": [plan(report=True)], "lead": [ask]})
    loop, team, _ = make(
        provider, tools=[Calculator], check_policy=lambda name: ("ask", "needs a person")
    )
    outcome = await go(loop, team)

    assert outcome.paused
    assert outcome.pending_tool_call is not None
    assert "writer" not in team.roles_used


async def test_a_resumed_run_does_not_route_or_run_helpers_again() -> None:
    provider = Cast({"router": [plan(("researcher", "again"))], "lead": [reply("Finished")]})
    loop, team, _ = make(
        provider,
        resume_from={
            "messages": [
                {"role": "system", "content": LEAD},
                {"role": "user", "content": "original"},
            ]
        },
    )
    outcome = await go(loop, team)

    assert outcome.output == "Finished"
    assert "router" not in provider.seen
    assert team.calls == 0


async def test_cancelling_stops_the_lead() -> None:
    provider = Cast({"router": [plan()], "lead": [reply("never")]})

    async def cancelled() -> bool:
        return True

    loop, team, _ = make(provider, is_cancelled=cancelled)
    outcome = await go(loop, team)
    assert outcome.stop_cause == "cancelled"


def test_the_graph_has_the_planned_nodes() -> None:
    from app.agent.supervisor import build_supervisor

    provider = Cast({})
    loop, team, _ = make(provider)
    nodes = set(build_supervisor(loop, team).get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"router", "helper", "lead", "writer", "critic", "finish"}
