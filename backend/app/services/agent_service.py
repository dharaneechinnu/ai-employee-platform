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
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.routing import Preference
from app.agent.schedule import Schedule, next_run
from app.agent.tool_infer import NEVER_GIVEN, infer_tools
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.models.agent import DEFAULT_RUN_STEPS, MAX_AGENTS, MAX_RUN_STEPS, Agent
from app.db.models.conversation import Conversation
from app.db.models.policy import Connection
from app.db.models.task import Run, Task
from app.services.conversation_service import ConversationService
from app.services.provider_service import AUTO_MODEL


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
        schedule: Schedule | None = None,
        scope: dict[str, object] | None = None,
        max_steps: int = DEFAULT_RUN_STEPS,
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
            tools_auto=tools is None,
            scope=self._check_scope(scope),
            max_steps=self._check_steps(max_steps),
        )
        self.choose_tools(agent, connected=await self._connected())
        self.apply_schedule(agent, schedule)
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
        schedule: Schedule | None = None,
        set_schedule: bool = False,
        scope: dict[str, object] | None = None,
        max_steps: int | None = None,
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
            # No list given means "pick them for me".
            agent.tools_auto = tools is None
        if scope is not None:
            agent.scope = self._check_scope(scope)
        if max_steps is not None:
            agent.max_steps = self._check_steps(max_steps)
        # Worked out again when the words that describe the job changed.
        refresh = instructions is not None or description is not None
        if refresh or agent.tools is None:
            self.choose_tools(agent, refresh=refresh, connected=await self._connected())
        if set_schedule:
            self.apply_schedule(agent, schedule)
        await self.session.flush()
        return agent

    async def _connected(self) -> set[str]:
        """The kinds of app this person has connected and switched on."""
        rows = await self.session.scalars(
            select(Connection.kind).where(
                Connection.owner_id == self.owner_id, Connection.enabled.is_(True)
            )
        )
        return {kind.value for kind in rows.all()}

    @staticmethod
    def choose_tools(
        agent: Agent, *, refresh: bool = False, connected: set[str] | None = None
    ) -> None:
        """Give an agent the tools its instructions call for.

        An agent with no list (one made before this existed, or one that
        asked to be set up automatically) gets one now. An automatic list
        is worked out again when `refresh` is set. A list somebody chose
        by hand is never touched. `connected` decides which app "my email"
        or "my calendar" means; without it, Google.
        """
        if agent.tools is None:
            agent.tools_auto = True
        if agent.tools_auto and (agent.tools is None or refresh):
            agent.tools = infer_tools(
                agent.name, agent.description, agent.instructions, connected=connected
            )

    # --- running on its own ----------------------------------------

    @staticmethod
    def apply_schedule(agent: Agent, schedule: Schedule | None) -> None:
        """Set or clear when the agent runs by itself. A new schedule
        starts switched on, so the next run is the next matching time."""
        if schedule is None:
            agent.schedule, agent.schedule_enabled, agent.next_run_at = None, False, None
            return
        # An unattended run is limited to named tools, never "everything".
        AgentService.choose_tools(agent)
        agent.schedule = schedule.model_dump()
        agent.schedule_enabled = True
        agent.next_run_at = next_run(schedule, datetime.now(UTC))

    async def pause(self, agent_id: uuid.UUID) -> Agent:
        agent = await self.get(agent_id)
        agent.schedule_enabled, agent.next_run_at = False, None
        await self.session.flush()
        return agent

    async def resume(self, agent_id: uuid.UUID) -> Agent:
        agent = await self.get(agent_id)
        if not agent.schedule:
            raise ValidationError("This agent has no schedule. Set a time first.")
        self.apply_schedule(agent, Schedule.model_validate(agent.schedule))
        await self.session.flush()
        return agent

    async def archive(self, agent_id: uuid.UUID) -> None:
        """Remove it from use. Chats that used it keep reading fine."""
        agent = await self.get(agent_id)
        agent.archived = True
        agent.schedule_enabled, agent.next_run_at = False, None
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
    def _check_scope(scope: dict[str, object] | None) -> dict[str, object]:
        """Only the one key is understood: the spreadsheets it may write to."""
        ids = (scope or {}).get("sheet_ids") or []
        if not isinstance(ids, list):
            raise ValidationError("sheet_ids must be a list.")
        from app.agent.tools.packs.sheets import spreadsheet_id

        cleaned = [spreadsheet_id(str(i)) for i in ids]
        if any(c is None for c in cleaned):
            raise ValidationError("A spreadsheet must be given as its address or its id.")
        return {"sheet_ids": list(dict.fromkeys(c for c in cleaned if c))}

    @staticmethod
    def _check_steps(steps: int) -> int:
        if not 5 <= steps <= MAX_RUN_STEPS:
            raise ValidationError(f"Steps per run must be between 5 and {MAX_RUN_STEPS}.")
        return steps

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
