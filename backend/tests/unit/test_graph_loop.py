"""Step 4c: the loop as a graph whose approval pause is saved by LangGraph.

These tests use LangGraph's in-memory saver, so they cover the loop's own
rules. Saving to Postgres, restarts and owner scoping are tested in
tests/integration/test_graph_checkpoints.py.
"""

import uuid
from typing import Any, ClassVar

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from app.agent.graph_loop import GraphLoop
from app.agent.loop import AgentLoop, Budget, StopCause
from app.agent.providers.base import (
    LLMError,
    LLMProvider,
    LLMReply,
    Message,
    ProviderRequestError,
    Role,
    StopReason,
    ToolCall,
    Usage,
)
from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult

CTX = ToolContext(owner_id=uuid.uuid4())


class Args(BaseModel):
    value: str = ""


class Counter:
    runs: ClassVar[list[str]] = []


class Sends(Tool):
    name = "sends"
    pack = "t"
    description = "Sends something"
    args_model = Args
    side_effect = SideEffect.WRITE

    async def run(self, ctx: ToolContext, args: Args) -> ToolResult:  # type: ignore[override]
        Counter.runs.append(f"sends:{args.value}")
        return ToolResult.success(f"sent {args.value}")


class Looks(Tool):
    name = "looks"
    pack = "t"
    description = "Looks at something"
    args_model = Args
    side_effect = SideEffect.READ

    async def run(self, ctx: ToolContext, args: Args) -> ToolResult:  # type: ignore[override]
        Counter.runs.append(f"looks:{args.value}")
        return ToolResult.success(f"saw {args.value}")


class Scripted(LLMProvider):
    provider_key = "scripted"

    def __init__(self, replies: list[Any]) -> None:
        super().__init__(api_key="x")
        self.replies = replies
        self.seen: list[list[Message]] = []

    async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
        self.seen.append(list(kwargs["messages"]))
        item = self.replies[min(len(self.seen) - 1, len(self.replies) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    async def check(self, model: str) -> None:
        return None


def says(text: str) -> LLMReply:
    return LLMReply(
        message=Message(role=Role.ASSISTANT, content=text),
        stop_reason=StopReason.END_TURN,
        usage=Usage(10, 5),
        model="m",
    )


def asks(*calls: tuple[str, str, str]) -> LLMReply:
    return LLMReply(
        message=Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(id=i, name=n, arguments={"value": v}) for i, n, v in calls],
        ),
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(10, 5),
        model="m",
    )


def policy(rules: dict[str, str]):
    return lambda name: (rules.get(name, "auto"), f"rule for {name}")


def make(
    provider: Scripted,
    saver: InMemorySaver,
    *,
    thread: str = "run-1",
    resume: bool = False,
    tools: list[type[Tool]] | None = None,
    rules: dict[str, str] | None = None,
    **kwargs: Any,
) -> GraphLoop:
    return GraphLoop(
        saver=saver,
        thread_id=thread,
        resume=resume,
        provider=provider,
        model="m",
        tools=tools if tools is not None else [Sends, Looks],
        tool_context=CTX,
        budget=kwargs.pop("budget", Budget(max_steps=8)),
        check_policy=policy(rules or {}),
        **kwargs,
    )


async def start(loop: GraphLoop, task: str = "do it"):
    return await loop.run(system_prompt="sys", task=task)


def setup_function() -> None:
    Counter.runs = []


# ---------------------------------------------------------------- the basics


async def test_it_answers_and_uses_a_tool_like_the_plain_loop() -> None:
    script = [asks(("c1", "looks", "a")), says("Done.")]
    graph = await start(make(Scripted(script), InMemorySaver()))
    plain = await AgentLoop(
        provider=Scripted(script),
        model="m",
        tools=[Sends, Looks],
        tool_context=CTX,
        budget=Budget(max_steps=8),
    ).run(system_prompt="sys", task="do it")

    assert graph.completed and graph.output == plain.output == "Done."
    assert graph.steps == plain.steps == 2
    assert (graph.prompt_tokens, graph.output_tokens) == (plain.prompt_tokens, plain.output_tokens)
    assert [e.type for e in graph.events] == [e.type for e in plain.events]


async def test_a_finished_run_leaves_no_saved_state_behind() -> None:
    saver = InMemorySaver()
    await start(make(Scripted([says("hi")]), saver))
    assert saver.storage == {} or not saver.storage.get("run-1")


async def test_history_is_placed_between_the_instructions_and_the_request() -> None:
    provider = Scripted([says("ok")])
    loop = make(provider, InMemorySaver())
    await loop.run(
        system_prompt="sys",
        task="now",
        history=[
            Message(role=Role.USER, content="before"),
            Message(role=Role.ASSISTANT, content="r"),
        ],
    )
    assert [m.content for m in provider.seen[0]] == ["sys", "before", "r", "now"]


async def test_parallel_calls_each_get_an_answer_in_order() -> None:
    provider = Scripted(
        [asks(("a", "looks", "1"), ("b", "looks", "2"), ("c", "looks", "3")), says("ok")]
    )
    outcome = await start(make(provider, InMemorySaver()))
    assert outcome.completed
    tool_replies = [m for m in provider.seen[1] if m.role is Role.TOOL]
    assert [m.tool_call_id for m in tool_replies] == ["a", "b", "c"]
    assert "parallel_started" in [e.type for e in outcome.events]


# ------------------------------------------------------------- stop reasons


async def test_it_stops_at_the_step_limit() -> None:
    provider = Scripted([asks(("c", "looks", "x"))])  # never finishes
    outcome = await start(make(provider, InMemorySaver(), budget=Budget(max_steps=3)))
    assert outcome.stop_cause == StopCause.MAX_STEPS
    assert outcome.steps == 3


async def test_a_provider_error_ends_the_run_with_the_reason() -> None:
    outcome = await start(make(Scripted([LLMError("rate limited")]), InMemorySaver()))
    assert outcome.stop_cause == StopCause.PROVIDER_ERROR
    assert outcome.output == "rate limited"


async def test_cancelling_stops_before_the_next_step() -> None:
    async def cancelled() -> bool:
        return True

    outcome = await start(make(Scripted([says("never")]), InMemorySaver(), is_cancelled=cancelled))
    assert outcome.stop_cause == StopCause.CANCELLED


async def test_a_model_that_cannot_take_tools_still_answers() -> None:
    refuse = ProviderRequestError("this model does not support tool use", status_code=400)

    class Picky(Scripted):
        async def complete(self, **kwargs: Any) -> LLMReply:  # type: ignore[override]
            if kwargs.get("tools"):
                raise refuse
            return await super().complete(**kwargs)

    outcome = await start(make(Picky([says("From memory.")]), InMemorySaver()))
    assert outcome.completed and outcome.output == "From memory."
    assert "tools_unsupported" in [e.type for e in outcome.events]


async def test_a_blocked_tool_is_explained_and_not_run() -> None:
    provider = Scripted([asks(("c", "sends", "x")), says("Could not.")])
    outcome = await start(make(provider, InMemorySaver(), rules={"sends": "blocked"}))
    assert outcome.completed
    assert Counter.runs == []
    reply = next(m for m in provider.seen[1] if m.role is Role.TOOL)
    assert "not permitted" in (reply.content or "")
    assert "tool_blocked" in [e.type for e in outcome.events]


# -------------------------------------------------------- pausing and resuming


async def test_a_tool_that_needs_approval_pauses_before_anything_runs() -> None:
    saver = InMemorySaver()
    outcome = await start(
        make(Scripted([asks(("c1", "sends", "x"))]), saver, rules={"sends": "ask"})
    )

    assert outcome.paused
    assert outcome.pending_tool_call == {"id": "c1", "name": "sends", "arguments": {"value": "x"}}
    assert outcome.saved_state is None  # the state is in the saver, not on the outcome
    assert Counter.runs == []
    assert "approval_requested" in [e.type for e in outcome.events]


async def test_approving_runs_the_call_exactly_once_and_finishes() -> None:
    saver = InMemorySaver()
    rules = {"sends": "ask"}
    paused = await start(make(Scripted([asks(("c1", "sends", "x"))]), saver, rules=rules))
    assert paused.paused

    # A different worker, later: a fresh loop on the same saved thread.
    provider = Scripted([says("Sent it.")])
    resumed = await start(make(provider, saver, resume=True, rules=rules))

    assert resumed.completed and resumed.output == "Sent it."
    assert Counter.runs == ["sends:x"]
    assert "approval_granted" in [e.type for e in resumed.events]
    # The model saw the result of the approved call and was not asked to repeat it.
    last = provider.seen[0]
    assert [m.role for m in last][-2:] == [Role.ASSISTANT, Role.TOOL]
    assert last[-1].content == "sent x"


async def test_a_resumed_run_keeps_counting_its_steps_and_tokens() -> None:
    saver = InMemorySaver()
    rules = {"sends": "ask"}
    await start(make(Scripted([asks(("c1", "sends", "x"))]), saver, rules=rules))
    resumed = await start(make(Scripted([says("Done")]), saver, resume=True, rules=rules))
    assert resumed.steps == 2
    assert (resumed.prompt_tokens, resumed.output_tokens) == (20, 10)


async def test_reads_in_the_same_step_wait_for_the_approval_too() -> None:
    """Nothing in a step runs until every call that needs a person is answered,
    so a resumed step never repeats work."""
    saver = InMemorySaver()
    rules = {"sends": "ask"}
    step = asks(("a", "looks", "1"), ("b", "sends", "2"), ("c", "looks", "3"))
    paused = await start(make(Scripted([step]), saver, rules=rules))
    assert paused.paused and Counter.runs == []

    provider = Scripted([says("ok")])
    await start(make(provider, saver, resume=True, rules=rules))
    assert sorted(Counter.runs) == ["looks:1", "looks:3", "sends:2"]
    assert len(Counter.runs) == 3  # each exactly once
    replies = [m for m in provider.seen[0] if m.role is Role.TOOL]
    assert [m.tool_call_id for m in replies] == ["a", "b", "c"]


async def test_two_calls_needing_approval_pause_twice() -> None:
    saver = InMemorySaver()
    rules = {"sends": "ask"}
    step = asks(("a", "sends", "1"), ("b", "sends", "2"))
    first = await start(make(Scripted([step]), saver, rules=rules))
    assert first.paused and first.pending_tool_call["id"] == "a"

    second = await start(make(Scripted([step]), saver, resume=True, rules=rules))
    assert second.paused and second.pending_tool_call["id"] == "b"
    assert Counter.runs == []

    done = await start(make(Scripted([says("both")]), saver, resume=True, rules=rules))
    assert done.completed
    assert sorted(Counter.runs) == ["sends:1", "sends:2"]


async def test_resuming_with_nothing_saved_says_so_instead_of_guessing() -> None:
    outcome = await start(make(Scripted([says("x")]), InMemorySaver(), resume=True))
    assert outcome.stop_cause == "state_lost"
    assert Counter.runs == []


# ------------------------------------------------- inside the team graph (4b)


async def test_a_team_run_whose_lead_pauses_resumes_without_routing_again() -> None:
    from app.agent.supervisor import run_supervised
    from app.agent.team import Team
    from tests.unit.test_supervisor import LEAD, Cast, plan

    saver = InMemorySaver()
    rules = {"sends": "ask"}
    events: list[str] = []

    async def emit(type_: str, **payload: Any) -> None:
        events.append(type_)

    first = Cast(
        {
            "router": [plan(("analyst", "work it out"))],
            "analyst": [says("numbers")],
            "lead": [asks(("c1", "sends", "x"))],
        }
    )
    team = Team(provider=first, model="m", tools=[Looks], check_policy=policy({}), emit=emit)
    paused = await run_supervised(
        make(first, saver, rules=rules), team, system_prompt=LEAD, task="send it"
    )
    assert paused.paused and team.calls == 1  # the analyst worked once
    assert Counter.runs == []

    second = Cast({"router": [plan(("analyst", "again"))], "lead": [says("Sent.")]})
    team2 = Team(provider=second, model="m", tools=[Looks], check_policy=policy({}), emit=emit)
    done = await run_supervised(
        make(second, saver, resume=True, rules=rules), team2, system_prompt=LEAD, task="send it"
    )

    assert done.completed and done.output == "Sent."
    assert Counter.runs == ["sends:x"]
    assert "router" not in second.seen and team2.calls == 0
