"""AI Agents: the helpers a person designs, mostly by talking to the builder.

Making one by chat happens in an ordinary conversation in builder mode
(see conversations); the card it shows ends up here as a POST. Reading
`/agents/overview` gives the whole tab in one call: the agents, the
built-in starters, what each has cost, and the recent runs to draw.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.agent.assistant import MODES
from app.agent.routing import Preference
from app.agent.team import ROLES
from app.agent.tools.registry import registry
from app.api.v1.deps import ContextDep, SessionDep
from app.db.models.agent import MAX_AGENTS, Agent
from app.db.models.conversation import ChatMode
from app.services.agent_service import AgentService, Usage

router = APIRouter(prefix="/me/agents", tags=["agents"])


class UsageResponse(BaseModel):
    runs: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")


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


class UpdateAgentRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    instructions: str | None = Field(default=None, min_length=10, max_length=8000)
    model: str | None = Field(default=None, max_length=200)
    routing: Preference | None = None
    # Present and null means "everything I allow"; absent means unchanged.
    tools: list[str] | None = None


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
    )


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
        if m.key is not ChatMode.BUILDER
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
        if c.mode is not ChatMode.BUILDER
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
    )
    await session.commit()
    return _agent(agent, None)


@router.get("/{agent_id}", response_model=AgentResponse, summary="One agent")
async def get_agent(agent_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> AgentResponse:
    service = AgentService(session, ctx.owner_id)
    return _agent(await service.get(agent_id), (await service.usage_by_agent()).get(agent_id))


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
    )
    await session.commit()
    return _agent(agent, (await service.usage_by_agent()).get(agent_id))


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an agent")
async def delete_agent(agent_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> None:
    await AgentService(session, ctx.owner_id).archive(agent_id)
    await session.commit()
