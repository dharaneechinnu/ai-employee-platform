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
from app.agent.team import AskSpecialist, Team
from app.agent.tools.base import ToolContext
from app.agent.tools.packs.delegation import specialist_policy
from app.agent.tools.registry import registry
from app.core.crypto import SecretUnreadableError
from app.core.errors import NotFoundError
from app.core.observability import get_logger
from app.db.models.ai_employee import AIEmployee, AIEmployeeVersion
from app.db.models.conversation import Conversation
from app.db.models.identity import User
from app.db.models.policy import Approval, ApprovalStatus, RunCheckpoint
from app.db.models.task import LLMCall, Run, RunStatus, Task, TaskStatus
from app.db.session import get_sessionmaker
from app.schemas.ai_employee import EmployeeConfig
from app.services.approval_service import ApprovalService
from app.services.connection_service import ConnectionService
from app.services.conversation_service import ConversationService
from app.services.employee_service import build_system_prompt
from app.services.mcp_service import McpService
from app.services.notification_service import NotificationService, notify_safely
from app.services.policy_service import PolicyService
from app.services.provider_service import ProviderService
from app.services.task_service import EventWriter, estimate_cost

log = get_logger(__name__)

WORKER_ID = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"


async def run_task(ctx: dict[str, Any], task_id: str) -> dict[str, Any]:
    maker = get_sessionmaker()
    return await _execute(maker, uuid.UUID(task_id))


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

        # Who does the work: an AI Employee, or the personal assistant
        # of a conversation, which has no stored configuration and is
        # built from the conversation's own settings.
        chat = (
            await session.get(Conversation, task.conversation_id)
            if task.conversation_id is not None
            else None
        )
        employee = None
        if chat is not None:
            config = EmployeeConfig(
                model=chat.model,
                routing=Preference(chat.routing),
                max_steps=assistant.CHAT_MAX_STEPS,
                temperature=0.4,
                # Filled in below from `chat_tools`: a chat has every
                # tool its person can use, not a picked list.
                enabled_tools=[],
            )
        else:
            employee = await session.get(AIEmployee, task.employee_id) if task.employee_id else None
            version = (
                await session.get(AIEmployeeVersion, task.employee_version_id)
                if task.employee_version_id
                else None
            )
            if employee is None or version is None:  # pragma: no cover
                task.status = TaskStatus.FAILED
                await session.commit()
                return {"status": "failed", "reason": "configuration missing"}
            config = EmployeeConfig.model_validate(version.config)

        resuming = task.status is TaskStatus.AWAITING_APPROVAL
        run = None

        if resuming:
            # Continue the paused run. A new row would orphan the
            # checkpoint, which is keyed by run id, and the approved
            # call would be lost.
            run = await session.scalar(
                select(Run)
                .where(Run.task_id == task.id, Run.status == RunStatus.AWAITING_APPROVAL)
                .order_by(Run.attempt.desc())
                .limit(1)
            )
            if run is not None:
                run.status = RunStatus.RUNNING
                run.heartbeat_at = datetime.now(UTC)

        if run is None:
            run = Run(
                owner_id=task.owner_id,
                task_id=task.id,
                attempt=1,
                status=RunStatus.RUNNING,
                started_at=datetime.now(UTC),
                heartbeat_at=datetime.now(UTC),
                worker_id=WORKER_ID,
            )
            session.add(run)

        task.status = TaskStatus.RUNNING
        await session.flush()
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
        history = (
            await ConversationService(session, task.owner_id).history_before(task)
            if chat is not None
            else None
        )
        classify_usage = Usage()

        async def classify(candidates: list[Candidate]) -> TaskKind:
            return await _classify_with_ai(providers, candidates, task.input, classify_usage)

        try:
            choices = await providers.route(
                config.model,
                text=task.input,
                preference=config.routing,
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

        provider = FallbackProvider(options, on_switch=on_switch)
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

        def check_policy(tool_name: str) -> tuple[str, str]:
            if tool_name == AskSpecialist.name and chat is not None and chat.team:
                # Specialists can only read; their own steps are checked one by one.
                return "auto", "team mode is on for this conversation"
            decision = resolver.evaluate(tool_name)
            return decision.setting.value, decision.reason

        checkpoint = await session.get(RunCheckpoint, run_db.id)
        approved_call = None
        if checkpoint is not None:
            approval = await session.scalar(
                select(Approval)
                .where(
                    Approval.run_id == run_db.id,
                    Approval.status == ApprovalStatus.APPROVED,
                )
                .order_by(Approval.decided_at.desc())
                .limit(1)
            )
            if approval is not None:
                approved_call = checkpoint.pending_tool_call
                # Consume it, so a later pause in the same run does
                # not replay this call a second time.
                await session.delete(checkpoint)
                await session.flush()

        # The company's connected apps, resolved once per run (and
        # again on resume, so a token refreshed while the run waited
        # for approval is picked up). Tools receive only the grant
        # they declare; the model never sees any of it.
        grants = await ConnectionService(session, task.owner_id).resolve_grants()
        grants.update(await McpService(session, task.owner_id).grants())
        await session.commit()

        async def cancelled() -> bool:
            fresh = await session.scalar(select(Task.cancel_requested).where(Task.id == task_id))
            return bool(fresh)

        tools = (
            assistant.chat_tools(resolver, set(grants))
            if chat is not None
            else registry.for_employee(config.enabled_tools, extra=resolver.extra_tools)
        )
        context_config: dict[str, Any] = {
            # The memory tools need a session and to know which
            # employee is asking, so employee-scoped memories stay
            # private to that employee. A chat has no employee: its
            # memories belong to the person.
            "_session": session,
            "_employee_id": employee.id if employee else None,
        }

        team: Team | None = None
        if chat is not None and chat.team:
            # Orchestration: the lead may hand parts to specialists, who
            # use the same AI and the conversation's read-only tools.
            async def emit(type_: str, **payload: Any) -> None:
                await sink(AgentEvent(type=type_, payload=payload))

            team = Team(
                provider=provider,
                model=model,
                tools=tools,
                check_policy=specialist_policy(resolver),
                emit=emit,
                # With Automatic, each specialist gets the AI best at its
                # role: long reading, careful reasoning, good writing.
                provider_for=(
                    _team_router(await providers.candidates(), options, config.routing)
                    if len(options) > 1
                    else None
                ),
            )
            context_config["_team"] = team
            tools = [*tools, AskSpecialist]

        loop = AgentLoop(
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
            budget=Budget(max_steps=config.max_steps),
            temperature=config.temperature,
            on_event=sink,
            is_cancelled=cancelled,
            check_policy=check_policy,
            resume_from=checkpoint.state if checkpoint else None,
            approved_call=approved_call,
        )

        if chat is not None:
            person = await session.get(User, task.created_by)
            system_prompt = assistant.system_prompt(
                chat.mode,
                person=(person.full_name or None) if person else None,
                team=chat.team,
                tool_names=[t.name for t in tools],
            )
        else:
            assert employee is not None
            system_prompt = build_system_prompt(
                config, name=employee.name, job_title=employee.job_title
            )

        outcome = await loop.run(system_prompt=system_prompt, task=task.input, history=history)
        if team is not None:
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
                state=outcome.saved_state or {},
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
            )

    await session.commit()
    log.info("run_finished", run_id=str(run.id), status=str(status), cause=stop_cause)
    if task is not None:
        await notify_safely(NotificationService(session, run.owner_id).task_finished(task, run))
    return {"status": str(status), "stop_cause": stop_cause, "run_id": str(run.id)}


_STOP_MESSAGES = {
    "max_steps": "I used all my steps before finishing. Try a narrower question.",
    "max_tokens": "That answer grew too long for one turn. Try asking for less at once.",
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
        base_url = await providers.resolve_base_url(choice.provider_key)
        options.append(
            Option(
                provider=build_provider(choice.provider_key, api_key, base_url=base_url),
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


def _team_router(candidates: list[Candidate], options: list[Option], preference: Preference) -> Any:
    """For each specialist role, the person's AIs ranked for that role's
    kind of work, behind one fallback provider."""
    by_key = {o.provider_key: o for o in options}
    cache: dict[str, tuple[FallbackProvider, str, str]] = {}

    def provider_for(role: str) -> tuple[FallbackProvider, str, str]:
        if role not in cache:
            ranked = rank(candidates, ROLE_KIND.get(role, TaskKind.GENERAL), preference)
            ordered = [by_key[c.provider_key] for c in ranked if c.provider_key in by_key]
            fallback = FallbackProvider(ordered or options)
            first = fallback.current
            cache[role] = (fallback, first.model, f"{first.provider_key}:{first.model}")
        return cache[role]

    return provider_for
