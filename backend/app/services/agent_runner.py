"""Starting a run of an agent that works on its own.

An agent's runs are ordinary chat turns in a conversation of its own, so
each night's result can be opened and read like any chat, and everything
a turn already has comes along: the tools, the person's Permissions, the
cost record and the live run view. This only decides whether a run may
start, and writes the one message that starts it.

Before it starts, the readiness check runs again. A connection that
expired since the agent was made is found here, and the run does not
begin; the person is told which link broke instead of getting a night
of failed calls.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.routing import Preference
from app.core.errors import ValidationError
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation
from app.db.models.task import TERMINAL_STATUSES, Task
from app.services.agent_service import AgentService
from app.services.conversation_service import ConversationService
from app.services.live_feed import record_scheduler_event
from app.services.readiness_service import Readiness, ReadinessService

RUN_PROMPT = (
    "Run your job now. Work through your instructions in full, using your tools. "
    "When you are done, finish with a short summary: what you did, what changed, "
    "anything you skipped and why, and anything that needs the person's attention. "
    "Do not ask questions: nobody is watching this run."
)

SUMMARY_CHARS = 600


@dataclass(slots=True)
class StartResult:
    # "started", "needs_attention" (a link in the chain is broken) or
    # "busy" (the last run is still going).
    status: str
    task: Task | None = None
    readiness: Readiness | None = None
    message: str = ""


class AgentRunner:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    async def start(
        self, agent: Agent, *, user_id: uuid.UUID, trigger: str = "manual"
    ) -> StartResult:
        """`trigger` is "schedule" or "manual"; it is only written to the
        scheduler events the agent tree shows."""
        now = datetime.now(UTC)
        # A schedule must never start an agent with "everything".
        AgentService.choose_tools(agent)
        readiness = await ReadinessService(self.session, self.owner_id).check(
            agent.tools or [], scheduled=True, scope=agent.scope
        )
        if not readiness.ok:
            await self._note(
                agent,
                "connections_checked",
                ok=False,
                message=readiness.sentence(),
                broken=[c.title for c in readiness.problems][:5],
            )
            return self._attention(agent, now, readiness, readiness.sentence())

        conversations = ConversationService(self.session, self.owner_id)
        try:
            conversation = await self.conversation(agent, conversations)
        except ValidationError as exc:
            # Its chosen AI is no longer connected.
            await self._note(
                agent,
                "connections_checked",
                ok=False,
                message=exc.message,
                broken=["The AI this agent uses"],
            )
            return self._attention(agent, now, None, exc.message)
        await self._note(agent, "connections_checked", ok=True)

        turn = await conversations.latest_turn(conversation.id)
        if turn is not None and turn.status not in TERMINAL_STATUSES:
            await self._note(agent, "agent_skipped", message="The last run is still going.")
            return StartResult("busy", message="The last run is still going.")

        _, task = await conversations.send(conversation.id, text=RUN_PROMPT, user_id=user_id)
        task.agent_id = agent.id
        task.title = f"{agent.name}: run of {now:%d %b %H:%M} UTC"
        agent.last_run_at, agent.last_status, agent.last_summary = now, "running", None
        await self.session.flush()
        await self._note(agent, "agent_started", task_id=task.id, trigger=trigger)
        return StartResult("started", task=task, readiness=readiness)

    async def _note(
        self, agent: Agent, type_: str, *, task_id: uuid.UUID | None = None, **payload: object
    ) -> None:
        """One line in the scheduler log, for the live agent tree."""
        await record_scheduler_event(
            self.session,
            owner_id=self.owner_id,
            agent_id=agent.id,
            type_=type_,
            payload={"name": agent.name, **payload},
            task_id=task_id,
        )

    # ------------------------------------------------------------------

    async def conversation(self, agent: Agent, conversations: ConversationService) -> Conversation:
        """The agent's own chat: its runs are written here, and so are the
        messages the person sends it, so everything is in one place."""
        if agent.run_conversation_id is not None:
            existing = await self.session.get(Conversation, agent.run_conversation_id)
            if existing is not None and existing.owner_id == self.owner_id:
                return existing
        conversation = await conversations.create(
            agent_id=agent.id, routing=Preference(agent.routing)
        )
        conversation.title = f"{agent.name}: runs"
        agent.run_conversation_id = conversation.id
        return conversation

    @staticmethod
    def _attention(
        agent: Agent, now: datetime, readiness: Readiness | None, why: str
    ) -> StartResult:
        agent.last_run_at, agent.last_status = now, "needs_attention"
        agent.last_summary = why[:1000]
        return StartResult("needs_attention", readiness=readiness, message=why)
