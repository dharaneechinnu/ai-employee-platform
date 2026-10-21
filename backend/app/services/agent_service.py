"""Agents: create, change and use the helpers a person designs.

Agents are configuration only. Using one never widens what the person
has allowed: its tool list is intersected with their Permissions, and a
chat that uses it runs through the same loop, approvals and cost
tracking as any other.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.routing import Preference
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.models.agent import MAX_AGENTS, Agent
from app.db.models.conversation import Conversation
from app.db.models.task import Run, Task
from app.services.conversation_service import ConversationService
from app.services.provider_service import AUTO_MODEL

# Tools an agent may never be given: they exist for one chat only.
NEVER_GIVEN = {"propose_agent", "ask_specialist"}


def make_handle(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30]
    return slug or "agent"


@dataclass(slots=True)
class Usage:
    runs: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")


class AgentService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    async def active(self, *, include_archived: bool = False) -> list[Agent]:
        query = select(Agent).where(Agent.owner_id == self.owner_id)
        if not include_archived:
            query = query.where(Agent.archived.is_(False))
        return list((await self.session.scalars(query.order_by(Agent.created_at))).all())

    async def get(self, agent_id: uuid.UUID) -> Agent:
        agent = await self.session.scalar(
            select(Agent).where(Agent.id == agent_id, Agent.owner_id == self.owner_id)
        )
        if agent is None:
            raise NotFoundError("No such agent.")
        return agent

    async def create(
        self,
        *,
        name: str,
        description: str,
        instructions: str,
        model: str = AUTO_MODEL,
        routing: Preference = Preference.BALANCED,
        tools: list[str] | None = None,
    ) -> Agent:
        active = await self.session.scalar(
            select(func.count())
            .select_from(Agent)
            .where(Agent.owner_id == self.owner_id, Agent.archived.is_(False))
        )
        if (active or 0) >= MAX_AGENTS:
            raise ConflictError(f"You can have up to {MAX_AGENTS} agents. Remove one first.")
        agent = Agent(
            owner_id=self.owner_id,
            name=name.strip(),
            handle=await self._free_handle(make_handle(name)),
            description=description.strip(),
            instructions=instructions.strip(),
            model=await self._check_model(model),
            routing=routing.value,
            tools=self._check_tools(tools),
        )
        self.session.add(agent)
        await self.session.flush()
        return agent

    async def update(
        self,
        agent_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        model: str | None = None,
        routing: Preference | None = None,
        tools: list[str] | None = None,
        set_tools: bool = False,
    ) -> Agent:
        agent = await self.get(agent_id)
        if name is not None:
            agent.name = name.strip() or agent.name
        if description is not None:
            agent.description = description.strip()
        if instructions is not None:
            agent.instructions = instructions.strip() or agent.instructions
        if model is not None:
            agent.model = await self._check_model(model)
        if routing is not None:
            agent.routing = routing.value
        if set_tools:
            agent.tools = self._check_tools(tools)
        await self.session.flush()
        return agent

    async def archive(self, agent_id: uuid.UUID) -> None:
        """Remove it from use. Chats that used it keep reading fine."""
        agent = await self.get(agent_id)
        agent.archived = True
        # Free the handle for a new agent with the same name.
        agent.handle = f"{agent.handle[:28]}~{uuid.uuid4().hex[:6]}"
        await self.session.execute(
            update(Conversation).where(Conversation.agent_id == agent.id).values(agent_id=None)
        )

    # --- what a run needs ------------------------------------------

    async def for_chat(self, agent_id: uuid.UUID | None) -> Agent | None:
        if agent_id is None:
            return None
        agent = await self.session.scalar(
            select(Agent).where(
                Agent.id == agent_id, Agent.owner_id == self.owner_id, Agent.archived.is_(False)
            )
        )
        return agent

    # --- cost -------------------------------------------------------

    async def usage_by_agent(self) -> dict[uuid.UUID | None, Usage]:
        """Runs, tokens and estimated cost per agent. `None` is the
        plain assistant (chats with no agent chosen)."""
        rows = await self.session.execute(
            select(
                Conversation.agent_id,
                func.count(Run.id),
                func.coalesce(func.sum(Run.prompt_tokens), 0),
                func.coalesce(func.sum(Run.output_tokens), 0),
                func.coalesce(func.sum(Run.cost_usd), 0),
            )
            .select_from(Run)
            .join(Task, Task.id == Run.task_id)
            .join(Conversation, Conversation.id == Task.conversation_id)
            .where(Run.owner_id == self.owner_id)
            .group_by(Conversation.agent_id)
        )
        return {
            agent_id: Usage(
                runs=int(n), prompt_tokens=int(p), output_tokens=int(o), cost_usd=Decimal(c)
            )
            for agent_id, n, p, o, c in rows.all()
        }

    async def recent_runs(self, limit: int = 12) -> list[tuple[Run, Task, Conversation]]:
        rows = await self.session.execute(
            select(Run, Task, Conversation)
            .join(Task, Task.id == Run.task_id)
            .join(Conversation, Conversation.id == Task.conversation_id)
            .where(Run.owner_id == self.owner_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
        )
        return [(r, t, c) for r, t, c in rows.all()]

    # --- checks -----------------------------------------------------

    async def _free_handle(self, base: str) -> str:
        taken = set(
            (
                await self.session.scalars(
                    select(Agent.handle).where(
                        Agent.owner_id == self.owner_id, Agent.handle.like(f"{base}%")
                    )
                )
            ).all()
        )
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    @staticmethod
    def _check_tools(tools: list[str] | None) -> list[str] | None:
        if tools is None:
            return None
        cleaned = [t.strip() for t in tools if t.strip()]
        if bad := sorted(set(cleaned) & NEVER_GIVEN):
            raise ValidationError(f"An agent cannot be given {', '.join(bad)}.")
        return list(dict.fromkeys(cleaned))

    async def _check_model(self, model: str) -> str:
        return await ConversationService(self.session, self.owner_id)._check_model(model)
