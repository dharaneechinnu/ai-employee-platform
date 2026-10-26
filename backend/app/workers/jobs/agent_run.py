"""Run one task.

This is the slow half of the split: the API queued a row and answered
in milliseconds, and this does the work that takes minutes.

Every step is written to Postgres before being published to Redis, so
a dropped publish costs a live update but never a record.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent import assistant
from app.agent.checkpoint import SqlCheckpointSaver
from app.agent.graph import run_in_graph
from app.agent.graph_loop import GraphLoop
from app.agent.loop import AgentEvent, AgentLoop, Budget, StopCause
from app.agent.providers import build_provider
from app.agent.providers.base import LLMError, Message, Role, Usage
from app.agent.providers.fallback import FallbackProvider, Option
from app.agent.routing import (
    CLASSIFY_PROMPT,
    Candidate,
    Choice,
    Preference,
    TaskKind,
    parse_kind,
    rank,
)
from app.agent.supervisor import run_supervised
from app.agent.team import AskSpecialist, Team, specialist_policy
from app.agent.tools import sheet_log
from app.agent.tools.base import ToolContext
from app.agent.tools.packs.builder import ProposeAgent, ProposeAgentArgs
from app.agent.tools.packs.sheets import sheet_ids_in
from app.agent.tools.registry import registry
from app.config import get_settings
from app.core.crypto import SecretUnreadableError
from app.core.errors import NotFoundError
from app.core.observability import get_logger
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation
from app.db.models.identity import User
from app.db.models.task import LLMCall, Run, RunStatus, Task, TaskStatus
from app.db.session import get_sessionmaker
from app.services.agent_service import AgentService
from app.services.approval_service import ApprovalService
from app.services.connection_service import ConnectionService
from app.services.conversation_service import ConversationService
from app.services.notification_service import NotificationService, notify_safely
from app.services.policy_service import PolicyService
from app.services.provider_service import ProviderService
from app.services.task_service import EventWriter, estimate_cost
from app.workers.jobs.run_steps import claim_run, narrow_to_agent, policy_check, take_approved_call

log = get_logger(__name__)

WORKER_ID = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"


async def run_task(ctx: dict[str, Any], task_id: str) -> dict[str, Any]:
    maker = get_sessionmaker()
    return await _execute(maker, uuid.UUID(task_id))


# Lower than a task agent's default: a conversation wants a steady,
# repeatable answer more than a surprising one.
CHAT_TEMPERATURE = 0.4

# A run nobody is watching may take longer than a chat turn, but must
# end before the worker's own job timeout (900 s) cuts it off.
UNATTENDED_SECONDS = 840.0


async def _execute(maker: async_sessionmaker, task_id: uuid.UUID) -> dict[str, Any]:  # type: ignore[type-arg]
    async with maker() as session:
        task = await session.scalar(select(Task).where(Task.id == task_id))
        if task is None:
            log.warning("run_task_missing", task_id=str(task_id))
            return {"status": "missing"}

        if task.status not in (TaskStatus.QUEUED, TaskStatus.AWAITING_APPROVAL):
            # Already picked up, cancelled, or finished. Re-delivery is
            # normal with a queue, so this is a no-op rather than an error.
            return {"status": str(task.status)}

        # The personal assistant of a conversation. It has no stored
        # configuration: it is built from the conversation's own
        # settings, and has every tool its person can use.
        chat = await session.get(Conversation, task.conversation_id)
        if chat is None:  # pragma: no cover - the foreign key guarantees it
            task.status = TaskStatus.FAILED
            await session.commit()
            return {"status": "failed", "reason": "conversation missing"}
        routing = Preference(chat.routing)

        run, continued = await claim_run(session, task, worker_id=WORKER_ID)
        await session.commit()

    # A fresh session for the run itself: the agent loop can take
    # minutes, and holding a connection open that long starves the pool.
    async with maker() as session:
        run_db = await session.get(Run, run.id)
        assert run_db is not None
        writer = EventWriter(session, run_db.id, task.owner_id)

        providers = ProviderService(session, task.owner_id)
        # A chat's history is read first: a long conversation is itself
        # a reason to pick an AI that handles long context well.
        history = await ConversationService(session, task.owner_id).history_before(task)
        classify_usage = Usage()

        async def classify(candidates: list[Candidate]) -> TaskKind:
            return await _classify_with_ai(providers, candidates, task.input, classify_usage)

        try:
            choices = await providers.route(
                chat.model,
                text=task.input,
                preference=routing,
                history_chars=sum(len(m.content or "") for m in history or []),
                classify=classify,
            )
            options = await _options(providers, choices)
        except SecretUnreadableError:
            await writer.append("run_stopped", {"cause": "provider_key_unreadable"})
            return await _finish(
                session,
                run_db,
                task_id,
                RunStatus.FAILED,
                stop_cause="provider_key_unreadable",
                error=(
                    "The saved AI key can no longer be read. "
                    "Enter it again under AI Providers, then try again."
                ),
            )
        except NotFoundError as exc:
            # No key connected. A clear message beats a mysterious
            # failure three steps into a run.
            await writer.append("run_stopped", {"cause": "provider_not_connected"})
            detail = (
                str(exc)
                if "Private only" in str(exc)
                else (
                    "No AI key is connected for the chosen model. "
                    "Connect one under AI Providers, then try again."
                )
            )
            return await _finish(
                session,
                run_db,
                task_id,
                RunStatus.FAILED,
                stop_cause="provider_not_connected",
                error=detail,
            )

        # Parallel tool calls and parallel specialists all report here,
        # and one database session cannot be used by two at once.
        sink_lock = asyncio.Lock()

        async def sink(event: AgentEvent) -> None:
            async with sink_lock:
                await writer.append(event.type, event.payload)
                run_db.heartbeat_at = datetime.now(UTC)
                await session.commit()

        # Several AIs behind one provider: the best for this task first,
        # the rest ready in case it is rate-limited or down.
        chosen = choices[0]
        switches: list[str] = []

        async def on_switch(old: Option, new: Option, exc: LLMError) -> None:
            names = {c.provider_key: c.display_name for c in choices}
            switches.append(
                f"{names.get(old.provider_key, old.provider_key)} was unavailable, "
                f"so {names.get(new.provider_key, new.provider_key)} took over"
            )
            await sink(
                AgentEvent(
                    type="model_fallback",
                    payload={
                        "from": f"{old.provider_key}:{old.model}",
                        "to": f"{new.provider_key}:{new.model}",
                        "error": type(exc).__name__,
                    },
                )
            )

        async def on_retry(option: Option, exc: LLMError, attempt: int, delay: float) -> None:
            await sink(
                AgentEvent(
                    type="model_retry",
                    payload={
                        "model": f"{option.provider_key}:{option.model}",
                        "error": type(exc).__name__,
                        "attempt": attempt,
                        "wait_s": delay,
                    },
                )
            )

        provider = FallbackProvider(options, on_switch=on_switch, on_retry=on_retry)
        model = options[0].model
        await sink(
            AgentEvent(
                type="model_chosen",
                payload={
                    "model": f"{options[0].provider_key}:{model}",
                    "name": chosen.display_name,
                    "kind": chosen.kind.value,
                    "preference": chosen.preference.value,
                    "reason": chosen.reason,
                    "fallbacks": len(options) - 1,
                },
            )
        )

        resolver = await PolicyService(session, task.owner_id).resolver()
        # Started by an agent's schedule or its Run now button: nobody is
        # watching, so nothing may wait for a person to approve it.
        unattended = task.agent_id is not None
        team_on = chat.team and not unattended
        # Team mode as a graph (router, helpers, review) rather than the lead
        # calling `ask_specialist` itself. See `agent/supervisor.py`.
        supervised = team_on and get_settings().agent_supervisor

        check_policy = policy_check(resolver, unattended=unattended, team_on=team_on)

        checkpoint, approved_call = await take_approved_call(session, run_db.id)

        # The person's connected apps, resolved once per run (and
        # again on resume, so a token refreshed while the run waited
        # for approval is picked up). Tools receive only the grant
        # they declare; the model never sees any of it.
        grants = await ConnectionService(session, task.owner_id).resolve_grants()
        await session.commit()

        async def cancelled() -> bool:
            fresh = await session.scalar(select(Task.cancel_requested).where(Task.id == task_id))
            return bool(fresh)

        tools = assistant.chat_tools(resolver, set(grants))
        agent_row = await AgentService(session, task.owner_id).for_chat(chat.agent_id)
        offered = None
        if agent_row is not None:
            tools = narrow_to_agent(tools, agent_row.tools)
        elif agent_row is None and _talks_about_agents(task.input, history):
            # Designing an agent. Only the ordinary assistant may: a saved
            # agent or a scheduled run cannot create agents. Every tool is
            # listed, connected or not, because the draft's checks are what
            # tell the person which app still needs connecting.
            offered = registry.all()
            tools = [*tools, ProposeAgent]
        # The memory tools need the run's session. What they remember
        # belongs to the person.
        # What the sheet tools really did, for the closing block of the reply.
        context_config: dict[str, Any] = {"_session": session, sheet_log.KEY: []}
        sheet_ids = sheet_ids_in(agent_row.scope) if agent_row else []
        if agent_row is not None:
            context_config["_agent_id"] = agent_row.id
            if sheet_ids or unattended:
                # Checked inside the sheet tools, so no instruction can lift it.
                # A list that grows: a sheet the agent creates joins it.
                context_config["allowed_sheet_ids"] = list(sheet_ids)

        team: Team | None = None
        if team_on:
            # Orchestration: the lead may hand parts to specialists, who
            # use the same AI and the conversation's read-only tools.
            async def emit(type_: str, **payload: Any) -> None:
                await sink(AgentEvent(type=type_, payload=payload))

            team_router = (
                TeamRouter(await providers.candidates(), options, routing)
                if len(options) > 1
                else None
            )
            team = Team(
                provider=provider,
                model=model,
                tools=tools,
                check_policy=specialist_policy(resolver),
                emit=emit,
                # With Automatic, each specialist gets the AI best at its
                # role: long reading, careful reasoning, good writing.
                provider_for=team_router,
                escalate_for=(team_router.stronger if team_router is not None else None),
            )
            context_config["_team"] = team
            if not supervised:
                tools = [*tools, AskSpecialist]

        loop_args: dict[str, Any] = dict(  # noqa: C408 - keyword form reads best here
            provider=provider,
            model=model,
            tools=tools,
            tool_context=ToolContext(
                owner_id=task.owner_id,
                run_id=run_db.id,
                dry_run=task.dry_run,
                grants=grants,
                config=context_config,
            ),
            budget=(
                Budget(max_steps=agent_row.max_steps, max_seconds=UNATTENDED_SECONDS)
                if unattended and agent_row is not None
                else Budget(max_steps=assistant.CHAT_MAX_STEPS)
            ),
            temperature=CHAT_TEMPERATURE,
            on_event=sink,
            is_cancelled=cancelled,
            check_policy=check_policy,
        )
        # A run paused under the old snapshot resumes the old way; every other
        # run uses the graph loop when it is switched on.
        if get_settings().agent_checkpointer and checkpoint is None:
            loop: AgentLoop = GraphLoop(
                saver=SqlCheckpointSaver(maker, task.owner_id),
                thread_id=str(run_db.id),
                resume=continued,
                **loop_args,
            )
        else:
            loop = AgentLoop(
                **loop_args,
                resume_from=checkpoint.state if checkpoint else None,
                approved_call=approved_call,
            )

        person = await session.get(User, task.created_by)
        system_prompt = assistant.system_prompt(
            chat.mode,
            person=(person.full_name or None) if person else None,
            team=team_on and not supervised,
            tool_names=[t.name for t in tools],
            persona=(
                (agent_row.name, _with_sheets(agent_row, sheet_ids, tools)) if agent_row else None
            ),
            offered=offered,
        )

        if supervised and team is not None:
            outcome = await run_supervised(
                loop, team, system_prompt=system_prompt, task=task.input, history=history
            )
        else:
            outcome = await run_in_graph(
                loop, system_prompt=system_prompt, task=task.input, history=history
            )
        if team is not None:
            if team.stats:
                await sink(AgentEvent(type="team_summary", payload=team.summary()))
            # The specialists' model calls are part of this turn's cost.
            outcome.prompt_tokens += team.prompt_tokens
            outcome.output_tokens += team.output_tokens
        # So is the tiny call that decided which AI to use, if one was made.
        outcome.prompt_tokens += classify_usage.prompt_tokens
        outcome.output_tokens += classify_usage.output_tokens
        # The AI that actually finished the run, after any fallback.
        provider_key, model = provider.current.provider_key, provider.current.model
        reason = chosen.reason + (f"; {switches[-1]}" if switches else "")

        if outcome.paused and outcome.pending_tool_call:
            call = outcome.pending_tool_call
            tool_cls = resolver.tool(call["name"])
            approval = await ApprovalService(session, task.owner_id).create(
                run_id=run_db.id,
                tool_name=call["name"],
                side_effect=tool_cls.side_effect.value if tool_cls else "write",
                # The full action, so the reviewer sees exactly what
                # they are agreeing to rather than a summary.
                proposed=call["arguments"],
                state=outcome.saved_state,
                pending_tool_call=call,
            )
            run_db.step_count = outcome.steps
            run_db.prompt_tokens = outcome.prompt_tokens
            run_db.output_tokens = outcome.output_tokens
            await session.commit()
            # After the commit, so the approval exists by the time
            # anyone clicks the link in the message.
            await notify_safely(
                NotificationService(session, task.owner_id).approval_requested(approval)
            )
            return {
                "status": "awaiting_approval",
                "stop_cause": outcome.stop_cause,
                "run_id": str(run_db.id),
            }

        cost = estimate_cost(provider_key, model, outcome.prompt_tokens, outcome.output_tokens)
        session.add(
            LLMCall(
                run_id=run_db.id,
                owner_id=task.owner_id,
                provider_key=provider_key,
                model=model,
                prompt_tokens=outcome.prompt_tokens,
                output_tokens=outcome.output_tokens,
                cost_usd=cost,
                created_at=datetime.now(UTC),
            )
        )

        run_db.step_count = outcome.steps
        run_db.prompt_tokens = outcome.prompt_tokens
        run_db.output_tokens = outcome.output_tokens
        run_db.cost_usd = cost
        run_db.output = outcome.output
        if outcome.completed and (
            sheets := sheet_log.closing(
                context_config[sheet_log.KEY],
                blocked=[
                    (str(e.payload.get("tool")), str(e.payload.get("reason")))
                    for e in outcome.events
                    if e.type == "tool_blocked"
                ],
            )
        ):
            run_db.output = f"{(outcome.output or '').rstrip()}\n\n{sheets}".strip()

        status = {
            StopCause.COMPLETED: RunStatus.COMPLETED,
            StopCause.CANCELLED: RunStatus.CANCELLED,
        }.get(outcome.stop_cause, RunStatus.FAILED)

        return await _finish(
            session,
            run_db,
            task_id,
            status,
            stop_cause=outcome.stop_cause,
            error=None if status is RunStatus.COMPLETED else outcome.output,
            model=f"{provider_key}:{model}",
            tools_used=_tools_used(outcome.events, team.roles_used if team else []),
            model_reason=reason,
            draft=_draft(outcome.events),
        )


async def _finish(
    session: Any,
    run: Run,
    task_id: uuid.UUID,
    status: RunStatus,
    *,
    stop_cause: str,
    error: str | None,
    model: str | None = None,
    tools_used: list[str] | None = None,
    model_reason: str | None = None,
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run.status = status
    run.stop_cause = stop_cause
    run.error_message = (error or None) if status is not RunStatus.COMPLETED else None
    run.ended_at = datetime.now(UTC)

    task = await session.get(Task, task_id)
    if task is not None:
        task.status = {
            RunStatus.COMPLETED: TaskStatus.COMPLETED,
            RunStatus.CANCELLED: TaskStatus.CANCELLED,
        }.get(status, TaskStatus.FAILED)
        if task.conversation_id is not None:
            # The reply goes into the conversation, finished or not, so
            # the thread always says what happened to each message.
            completed = status is RunStatus.COMPLETED
            await ConversationService(session, run.owner_id).record_reply(
                task,
                content=run.output if completed else None,
                model=model,
                error=None if completed else _chat_error(status, stop_cause, error),
                tools_used=tools_used,
                model_reason=model_reason,
                draft=draft,
            )
            if task.agent_id is not None:
                await _agent_ran(session, task, run=run, completed=status is RunStatus.COMPLETED)

    await session.commit()
    log.info("run_finished", run_id=str(run.id), status=str(status), cause=stop_cause)
    return {"status": str(status), "stop_cause": stop_cause, "run_id": str(run.id)}


async def _agent_ran(session: Any, task: Task, *, run: Run, completed: bool) -> None:
    """Record how an agent's own run went on the agent, and tell the person."""
    agent = await session.get(Agent, task.agent_id)
    if agent is None:
        return
    summary = (
        (run.output or "")
        if completed
        else _chat_error(run.status, run.stop_cause or "", run.error_message)
    )
    agent.last_run_at = datetime.now(UTC)
    agent.last_status = "completed" if completed else "failed"
    agent.last_summary = summary.strip()[:1000] or None
    await notify_safely(
        NotificationService(session, task.owner_id).agent_run_finished(
            agent, status=agent.last_status, summary=agent.last_summary or ""
        )
    )


_STOP_MESSAGES = {
    "max_steps": "I used all my steps before finishing. Try a narrower question.",
    "max_tokens": (
        "I used up my work limit before finishing, so some of the job may be undone. "
        "Try a narrower job, such as fewer places or fewer results at once."
    ),
    "timeout": "That took too long, so I stopped.",
    "provider_error": "The AI service returned an error.",
}


def _chat_error(status: RunStatus, stop_cause: str, error: str | None) -> str:
    """One plain sentence for the chat, with the technical detail after."""
    if status is RunStatus.CANCELLED:
        return "Stopped."
    sentence = _STOP_MESSAGES.get(stop_cause)
    if sentence and error:
        return f"{sentence} ({error[:300]})"
    return sentence or error or "Something went wrong before I could answer."


def _draft(events: list[AgentEvent]) -> dict[str, Any] | None:
    """The agent last proposed in this turn, if the assistant did. Checked
    again here: a draft with a time that is not a time must not reach a
    card the person could press Create on."""
    drafts = [
        e.payload.get("arguments")
        for e in events
        if e.type == "tool_call" and e.payload.get("tool") == ProposeAgent.name
    ]
    last = drafts[-1] if drafts else None
    if not isinstance(last, dict):
        return None
    try:
        return ProposeAgentArgs.model_validate(last).model_dump(mode="json")
    except ValueError:
        return None


def _with_sheets(agent: Agent, sheet_ids: list[str], tools: list[Any]) -> str:
    """The agent's instructions, plus which spreadsheet is its own. Said
    here, not left to the person to paste, so a sheet it created last
    night is the one it uses tonight."""
    text = agent.instructions
    if sheet_ids:
        links = ", ".join(f"https://docs.google.com/spreadsheets/d/{i}" for i in sheet_ids)
        text += f"\n\nYour spreadsheet: {links}. Use it. Do not create another."
    elif any(t.name == "sheets_create" for t in tools):
        text += (
            "\n\nYou have no spreadsheet yet. Create one with sheets_create, with the tabs "
            "and header rows your job needs, then keep using it."
        )
    return text


def _talks_about_agents(text: str, history: list[Message] | None) -> bool:
    """Whether this turn is about building an agent: the message, or the
    last few turns it follows, mention one."""
    recent = [m.content or "" for m in (history or [])[-6:]]
    return any(assistant.AGENT_INTENT.search(t) for t in (text, *recent))


def _tools_used(events: list[AgentEvent], roles: list[str]) -> list[str]:
    """Each tool the turn used, once, in first-use order, then each
    specialist asked as "specialist:<role>", so the chat can name both."""
    used: list[str] = []
    for event in events:
        tool = event.payload.get("tool")
        if event.type == "tool_call" and tool and tool != AskSpecialist.name:
            used.append(str(tool))
    used += [f"specialist:{role}" for role in roles]
    return list(dict.fromkeys(used))


# How long the "what kind of task is this?" call may take before the
# run goes ahead treating it as a general task.
CLASSIFY_TIMEOUT_S = 12.0

# Which kind of work each specialist role mostly does.
ROLE_KIND: dict[str, TaskKind] = {
    "researcher": TaskKind.LONG,
    "analyst": TaskKind.ANALYSIS,
    "writer": TaskKind.WRITING,
    "critic": TaskKind.ANALYSIS,
}


async def _options(providers: ProviderService, choices: list[Choice]) -> list[Option]:
    """A ready-to-call provider per choice, in order. A choice whose
    saved key cannot be read is skipped, unless it is the only one."""
    options: list[Option] = []
    unreadable: SecretUnreadableError | None = None
    for choice in choices:
        try:
            api_key = await providers.resolve_api_key(choice.provider_key)
        except SecretUnreadableError as exc:
            unreadable = exc
            continue
        endpoint = await providers.resolve_endpoint(choice.provider_key)
        options.append(
            Option(
                provider=build_provider(
                    choice.provider_key,
                    api_key,
                    base_url=endpoint.base_url,
                    api_format=endpoint.api_format,
                    auth_header=endpoint.auth_header,
                ),
                provider_key=choice.provider_key,
                model=choice.model,
            )
        )
    if not options:
        raise unreadable or NotFoundError("No AI is connected.")
    return options


async def _classify_with_ai(
    providers: ProviderService, candidates: list[Candidate], text: str, usage: Usage
) -> TaskKind:
    """Ask the cheapest connected AI what kind of task this is, in one
    tiny call. Any failure means "general": routing must never be the
    reason a run fails."""
    cheapest = rank(candidates, TaskKind.QUICK, Preference.COST)[0]
    try:
        [option] = await _options(
            providers,
            [
                Choice(
                    provider_key=cheapest.provider_key,
                    model=cheapest.model,
                    display_name=cheapest.display_name,
                    kind=TaskKind.GENERAL,
                    preference=Preference.COST,
                    reason="",
                )
            ],
        )
        reply = await asyncio.wait_for(
            option.provider.complete(
                messages=[
                    Message(role=Role.SYSTEM, content=CLASSIFY_PROMPT),
                    Message(role=Role.USER, content=text[:3000]),
                ],
                model=option.model,
                temperature=0.0,
                max_tokens=10,
            ),
            timeout=CLASSIFY_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 - see the docstring
        log.info("classify_failed", error=type(exc).__name__)
        return TaskKind.GENERAL
    usage.prompt_tokens += reply.usage.prompt_tokens
    usage.output_tokens += reply.usage.output_tokens
    return parse_kind(reply.text)


class TeamRouter:
    """For each specialist role, the person's AIs ranked for that role's
    kind of work, behind one fallback provider. `stronger` is the same
    ranked for quality alone, for a helper that failed on its first AI."""

    def __init__(
        self, candidates: list[Candidate], options: list[Option], preference: Preference
    ) -> None:
        self._candidates = candidates
        self._options = options
        self._by_key = {o.provider_key: o for o in options}
        self._preference = preference
        self._cache: dict[str, tuple[FallbackProvider, str, str]] = {}
        self._strong: dict[str, tuple[FallbackProvider, str, str] | None] = {}

    def _build(self, role: str, preference: Preference) -> tuple[FallbackProvider, str, str]:
        ranked = rank(self._candidates, ROLE_KIND.get(role, TaskKind.GENERAL), preference)
        ordered = [self._by_key[c.provider_key] for c in ranked if c.provider_key in self._by_key]
        fallback = FallbackProvider(ordered or self._options)
        first = fallback.current
        return fallback, first.model, f"{first.provider_key}:{first.model}"

    def __call__(self, role: str) -> tuple[FallbackProvider, str, str]:
        if role not in self._cache:
            self._cache[role] = self._build(role, self._preference)
        return self._cache[role]

    def stronger(self, role: str) -> tuple[FallbackProvider, str, str] | None:
        """The best AI for this role, or None when it is the one already used."""
        if role not in self._strong:
            # Private stays private; anything else is "best answer, whatever it costs".
            wanted = (
                Preference.PRIVATE if self._preference is Preference.PRIVATE else Preference.QUALITY
            )
            best = self._build(role, wanted)
            self._strong[role] = None if best[2] == self(role)[2] else best
        return self._strong[role]
