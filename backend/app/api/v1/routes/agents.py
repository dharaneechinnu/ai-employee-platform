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
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.agent.assistant import MODES
from app.agent.routing import Preference
from app.agent.schedule import Schedule, describe
from app.agent.team import ROLES
from app.agent.tools.packs.sheets import sheet_ids_in
from app.agent.tools.registry import registry
from app.api.v1.deps import ContextDep, SessionDep
from app.core.errors import ValidationError
from app.db.models.agent import DEFAULT_RUN_STEPS, MAX_AGENTS, MAX_RUN_STEPS, Agent
from app.services.agent_runner import AgentRunner
from app.services.agent_service import AgentService, Usage
from app.services.conversation_service import ConversationService
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
    if not agent.tools:
        raise ValidationError("Give this agent some tools before running it on its own.")
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
