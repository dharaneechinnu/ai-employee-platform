"""AI Agents: manage the helpers a person has made.

Agents are made in Chat: the person describes one, the assistant shows a
draft card, and pressing Create on that card is the POST below. This tab
is where they are managed afterwards: edited, scheduled, paused, run on
demand, and seen as a tree and as cost. Reading `/agents/overview` gives
the whole tab in one call.

Whether an agent could really do its job (its apps connected, the
permissions granted, the platform's say) is `readiness`, asked for a
draft before it exists and for a saved agent before it runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.agent.assistant import MODES
from app.agent.routing import Preference
from app.agent.schedule import Schedule, describe
from app.agent.team import ROLES
from app.agent.tools.packs.sheets import sheet_ids_in
from app.agent.tools.registry import registry
from app.api.v1.deps import ContextDep, SessionDep
from app.core.errors import ValidationError
from app.db.models.agent import DEFAULT_RUN_STEPS, MAX_AGENTS, MAX_RUN_STEPS, Agent
from app.db.models.conversation import Conversation
from app.db.models.task import Run, RunStatus, Task, TaskStatus
from app.services.agent_runner import AgentRunner
from app.services.agent_service import AgentService, Usage
from app.services.conversation_service import ConversationService
from app.services.live_feed import LiveFeed
from app.services.readiness_service import ReadinessService
from app.workers.queue import enqueue_task

router = APIRouter(prefix="/me/agents", tags=["agents"])


class UsageResponse(BaseModel):
    runs: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")


class ScopeBody(BaseModel):
    # The spreadsheets the agent may write to: addresses or ids.
    sheet_ids: list[str] = Field(default_factory=list, max_length=10)


class AgentResponse(BaseModel):
    id: uuid.UUID
    name: str
    handle: str
    description: str
    instructions: str
    model: str
    routing: Preference
    tools: list[str] | None
    # True when the list was worked out from the instructions.
    tools_auto: bool = False
    created_at: datetime
    usage: UsageResponse
    schedule: Schedule | None = None
    schedule_text: str | None = None
    schedule_enabled: bool = False
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_summary: str | None = None
    run_conversation_id: uuid.UUID | None = None
    max_steps: int = DEFAULT_RUN_STEPS
    scope: ScopeBody = Field(default_factory=ScopeBody)


class StarterResponse(BaseModel):
    key: str
    kind: str  # "mode" or "specialist"
    name: str
    description: str
    instructions: str


class ToolInfo(BaseModel):
    name: str
    pack: str
    description: str
    side_effect: str
    needs_app: str | None


class RunRow(BaseModel):
    run_id: uuid.UUID
    conversation_id: uuid.UUID
    title: str
    agent_id: uuid.UUID | None
    status: str
    cost_usd: Decimal
    prompt_tokens: int
    output_tokens: int
    started_at: datetime | None
    ended_at: datetime | None


class Overview(BaseModel):
    agents: list[AgentResponse]
    starters: list[StarterResponse]
    assistant_usage: UsageResponse
    tools: list[ToolInfo]
    recent_runs: list[RunRow]
    limit: int


class TreeAgent(BaseModel):
    id: uuid.UUID
    name: str
    # "idle", "working", "waiting" (for the person) or "failed".
    state: str
    next_run_at: datetime | None
    schedule_text: str | None
    last_summary: str | None
    active_run_id: uuid.UUID | None
    active_task_id: uuid.UUID | None


class TreeHelper(BaseModel):
    # Stable: the role's own key, so a node keeps its place between visits.
    key: str
    label: str


class TreeScheduler(BaseModel):
    next_run_at: datetime | None
    next_agent_id: uuid.UUID | None
    next_agent_name: str | None
    scheduled_count: int


class TreeLead(BaseModel):
    state: str
    active_run_id: uuid.UUID | None
    active_task_id: uuid.UUID | None


class Tree(BaseModel):
    now: datetime
    scheduler: TreeScheduler
    lead: TreeLead
    agents: list[TreeAgent]
    helpers: list[TreeHelper]
    # What the scheduler did in the last few minutes, oldest first.
    recent_scheduler: list[dict[str, Any]]
    # Where to start watching the live stream so nothing falls in the gap.
    cursor: str


class CreateAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    instructions: str = Field(min_length=10, max_length=8000)
    model: str = Field(default="auto", max_length=200)
    routing: Preference = Preference.BALANCED
    tools: list[str] | None = None
    schedule: Schedule | None = None
    scope: ScopeBody | None = None
    max_steps: int = Field(default=DEFAULT_RUN_STEPS, ge=5, le=MAX_RUN_STEPS)


class UpdateAgentRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    instructions: str | None = Field(default=None, min_length=10, max_length=8000)
    model: str | None = Field(default=None, max_length=200)
    routing: Preference | None = None
    # Present and null means "everything I allow"; absent means unchanged.
    tools: list[str] | None = None
    # Present and null removes the schedule; absent leaves it alone.
    schedule: Schedule | None = None
    scope: ScopeBody | None = None
    max_steps: int | None = Field(default=None, ge=5, le=MAX_RUN_STEPS)


class ReadinessRequest(BaseModel):
    tools: list[str] = Field(default_factory=list, max_length=80)
    # Whether it will run on its own: that is stricter (nothing may ask).
    scheduled: bool = False
    scope: ScopeBody | None = None


class CheckResponse(BaseModel):
    ok: bool
    layer: str
    title: str
    detail: str
    fix: str | None = None
    service: str | None = None
    level: str | None = None
    tool: str | None = None


class ReadinessResponse(BaseModel):
    ok: bool
    checks: list[CheckResponse]


class ChatTarget(BaseModel):
    conversation_id: uuid.UUID


class RunNowResponse(BaseModel):
    # "started", "needs_attention" or "busy".
    status: str
    message: str = ""
    task_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    readiness: ReadinessResponse | None = None


def _usage(u: Usage | None) -> UsageResponse:
    if u is None:
        return UsageResponse()
    return UsageResponse(
        runs=u.runs,
        prompt_tokens=u.prompt_tokens,
        output_tokens=u.output_tokens,
        cost_usd=u.cost_usd,
    )


def _agent(agent: Agent, usage: Usage | None) -> AgentResponse:
    schedule = Schedule.model_validate(agent.schedule) if agent.schedule else None
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        handle=agent.handle,
        description=agent.description,
        instructions=agent.instructions,
        model=agent.model,
        routing=Preference(agent.routing),
        tools=agent.tools,
        tools_auto=agent.tools_auto,
        created_at=agent.created_at,
        usage=_usage(usage),
        schedule=schedule,
        schedule_text=describe(schedule) if schedule else None,
        schedule_enabled=agent.schedule_enabled,
        next_run_at=agent.next_run_at,
        last_run_at=agent.last_run_at,
        last_status=agent.last_status,
        last_summary=agent.last_summary,
        run_conversation_id=agent.run_conversation_id,
        max_steps=agent.max_steps,
        scope=ScopeBody(sheet_ids=sheet_ids_in(agent.scope)),
    )


def _readiness(result: Any) -> ReadinessResponse:
    return ReadinessResponse(**result.as_dict())


def _scope(body: ScopeBody | None) -> dict[str, object] | None:
    return None if body is None else {"sheet_ids": body.sheet_ids}


@router.get("/overview", response_model=Overview, summary="Everything the AI Agents tab shows")
async def overview(ctx: ContextDep, session: SessionDep) -> Overview:
    service = AgentService(session, ctx.owner_id)
    usage = await service.usage_by_agent()
    starters = [
        StarterResponse(
            key=m.key.value,
            kind="mode",
            name=m.label,
            description=m.for_whom,
            instructions=m.instructions,
        )
        for m in MODES.values()
    ] + [
        StarterResponse(
            key=r.key,
            kind="specialist",
            name=r.label,
            description=r.instructions.split(".")[0] + ".",
            instructions=r.instructions,
        )
        for r in ROLES.values()
    ]
    tools = [
        ToolInfo(
            name=t.name,
            pack=t.pack,
            description=t.description,
            side_effect=t.side_effect.value,
            needs_app=t.requires_connection or None,
        )
        for t in registry.all()
    ]
    runs = [
        RunRow(
            run_id=r.id,
            conversation_id=c.id,
            title=c.title,
            agent_id=c.agent_id,
            status=str(r.status),
            cost_usd=r.cost_usd,
            prompt_tokens=r.prompt_tokens,
            output_tokens=r.output_tokens,
            started_at=r.started_at,
            ended_at=r.ended_at,
        )
        for r, _task, c in await service.recent_runs()
    ]
    return Overview(
        agents=[_agent(a, usage.get(a.id)) for a in await service.active()],
        starters=starters,
        assistant_usage=_usage(usage.get(None)),
        tools=tools,
        recent_runs=runs,
        limit=MAX_AGENTS,
    )


_ACTIVE_TASKS = (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.AWAITING_APPROVAL)
# Longer than this since a scheduler step, the tree does not replay it.
_RECENT_SCHEDULER = timedelta(minutes=10)


@router.get("/tree", response_model=Tree, summary="What the agent tree shows right now")
async def tree(ctx: ContextDep, session: SessionDep) -> Tree:
    """The tree's starting picture: each agent's state and next run, the
    scheduler's next start, and the runs going now. The live stream
    (`/me/live`) then keeps it moving. Everything is the caller's own."""
    feed = LiveFeed(session, ctx.owner_id)
    cursor = await feed.now()  # first, so an event after this is replayed, not lost
    now = datetime.now(UTC)

    # One row per task still going: its agent (from the schedule or the
    # agent's own chat), its run if a worker has picked it up, its state.
    rows = (
        await session.execute(
            select(
                Task.id,
                func.coalesce(Task.agent_id, Conversation.agent_id),
                Task.status,
                Run.id,
                Run.status,
            )
            .join(Conversation, Conversation.id == Task.conversation_id)
            .outerjoin(
                Run,
                (Run.task_id == Task.id)
                & Run.status.in_((RunStatus.RUNNING, RunStatus.AWAITING_APPROVAL)),
            )
            .where(Task.owner_id == ctx.owner_id, Task.status.in_(_ACTIVE_TASKS))
            .order_by(Task.created_at.desc())
            .limit(100)
        )
    ).all()
    active: dict[uuid.UUID | None, tuple[str, uuid.UUID, uuid.UUID | None]] = {}
    for task_id, agent_id, task_status, run_id, run_status in rows:
        waiting = TaskStatus.AWAITING_APPROVAL in (task_status, run_status)
        active.setdefault(agent_id, ("waiting" if waiting else "working", task_id, run_id))

    agents = list(await AgentService(session, ctx.owner_id).active())
    scheduled = sorted(
        (a for a in agents if a.schedule_enabled and a.next_run_at is not None),
        key=lambda a: a.next_run_at or now,
    )

    def _state(agent: Agent) -> str:
        if agent.id in active:
            return active[agent.id][0]
        return "failed" if agent.last_status in ("failed", "needs_attention") else "idle"

    lead_state, lead_task, lead_run = active.get(None, ("idle", None, None))
    return Tree(
        now=now,
        scheduler=TreeScheduler(
            next_run_at=scheduled[0].next_run_at if scheduled else None,
            next_agent_id=scheduled[0].id if scheduled else None,
            next_agent_name=scheduled[0].name if scheduled else None,
            scheduled_count=len(scheduled),
        ),
        lead=TreeLead(state=lead_state, active_run_id=lead_run, active_task_id=lead_task),
        agents=[
            TreeAgent(
                id=a.id,
                name=a.name,
                state=_state(a),
                next_run_at=a.next_run_at if a.schedule_enabled else None,
                schedule_text=(
                    describe(Schedule.model_validate(a.schedule)) if a.schedule else None
                ),
                last_summary=a.last_summary,
                active_run_id=active[a.id][2] if a.id in active else None,
                active_task_id=active[a.id][1] if a.id in active else None,
            )
            for a in agents
        ],
        helpers=[TreeHelper(key=r.key, label=r.label) for r in ROLES.values()],
        recent_scheduler=await feed.recent_scheduler_events(now - _RECENT_SCHEDULER),
        cursor=str(cursor),
    )


@router.post(
    "/readiness",
    response_model=ReadinessResponse,
    summary="Could an agent with these tools really do its job?",
)
async def readiness(
    body: ReadinessRequest, ctx: ContextDep, session: SessionDep
) -> ReadinessResponse:
    result = await ReadinessService(session, ctx.owner_id).check(
        body.tools, scheduled=body.scheduled, scope=_scope(body.scope)
    )
    return _readiness(result)


@router.post(
    "", response_model=AgentResponse, status_code=status.HTTP_201_CREATED, summary="Create an agent"
)
async def create_agent(
    body: CreateAgentRequest, ctx: ContextDep, session: SessionDep
) -> AgentResponse:
    agent = await AgentService(session, ctx.owner_id).create(
        name=body.name,
        description=body.description,
        instructions=body.instructions,
        model=body.model,
        routing=body.routing,
        tools=body.tools,
        schedule=body.schedule,
        scope=_scope(body.scope),
        max_steps=body.max_steps,
    )
    await session.commit()
    return _agent(agent, None)


@router.get("/{agent_id}", response_model=AgentResponse, summary="One agent")
async def get_agent(agent_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> AgentResponse:
    service = AgentService(session, ctx.owner_id)
    return _agent(await service.get(agent_id), (await service.usage_by_agent()).get(agent_id))


@router.get(
    "/{agent_id}/readiness",
    response_model=ReadinessResponse,
    summary="Could this saved agent run right now?",
)
async def agent_readiness(
    agent_id: uuid.UUID, ctx: ContextDep, session: SessionDep
) -> ReadinessResponse:
    agent = await AgentService(session, ctx.owner_id).get(agent_id)
    result = await ReadinessService(session, ctx.owner_id).check(
        agent.tools or [], scheduled=agent.schedule_enabled, scope=agent.scope
    )
    return _readiness(result)


@router.patch("/{agent_id}", response_model=AgentResponse, summary="Change an agent")
async def update_agent(
    agent_id: uuid.UUID, body: UpdateAgentRequest, ctx: ContextDep, session: SessionDep
) -> AgentResponse:
    service = AgentService(session, ctx.owner_id)
    agent = await service.update(
        agent_id,
        name=body.name,
        description=body.description,
        instructions=body.instructions,
        model=body.model,
        routing=body.routing,
        tools=body.tools,
        set_tools="tools" in body.model_fields_set,
        schedule=body.schedule,
        set_schedule="schedule" in body.model_fields_set,
        scope=_scope(body.scope),
        max_steps=body.max_steps,
    )
    await session.commit()
    return _agent(agent, (await service.usage_by_agent()).get(agent_id))


@router.post("/{agent_id}/pause", response_model=AgentResponse, summary="Stop its schedule")
async def pause_agent(agent_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> AgentResponse:
    service = AgentService(session, ctx.owner_id)
    agent = await service.pause(agent_id)
    await session.commit()
    return _agent(agent, (await service.usage_by_agent()).get(agent_id))


@router.post("/{agent_id}/resume", response_model=AgentResponse, summary="Start its schedule again")
async def resume_agent(agent_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> AgentResponse:
    service = AgentService(session, ctx.owner_id)
    agent = await service.resume(agent_id)
    await session.commit()
    return _agent(agent, (await service.usage_by_agent()).get(agent_id))


@router.post("/{agent_id}/run", response_model=RunNowResponse, summary="Run it now")
async def run_agent_now(
    agent_id: uuid.UUID, ctx: ContextDep, session: SessionDep
) -> RunNowResponse:
    agent = await AgentService(session, ctx.owner_id).get(agent_id)
    # An agent with no list (made before tools were chosen for it) gets one now.
    AgentService.choose_tools(agent)
    if not agent.tools:
        raise ValidationError(
            "This agent has no tools to work with. Describe its job in its instructions."
        )
    result = await AgentRunner(session, ctx.owner_id).start(agent, user_id=ctx.user_id)
    await session.commit()
    if result.task is not None:
        # After the commit: the worker must find the task when it picks it up.
        await enqueue_task(result.task.id)
    return RunNowResponse(
        status=result.status,
        message=result.message,
        task_id=result.task.id if result.task else None,
        conversation_id=agent.run_conversation_id,
        readiness=_readiness(result.readiness) if result.readiness else None,
    )


@router.post("/{agent_id}/chat", response_model=ChatTarget, summary="Open the agent's own chat")
async def agent_chat(agent_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> ChatTarget:
    agent = await AgentService(session, ctx.owner_id).get(agent_id)
    chat = await AgentRunner(session, ctx.owner_id).conversation(
        agent, ConversationService(session, ctx.owner_id)
    )
    await session.commit()
    return ChatTarget(conversation_id=chat.id)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an agent")
async def delete_agent(agent_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> None:
    await AgentService(session, ctx.owner_id).archive(agent_id)
    await session.commit()
