"""Conversations with the personal assistant.

Sending a message creates a task for the conversation; the worker runs
it with the agent loop, then writes the reply back here. Everything a
task already has (tools, approvals, cancel, the live run, cost) comes
along for free. This file adds only what a chat needs on top: threads,
history, modes, the model choice and the team switch.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.assistant import HISTORY_CHARS, HISTORY_MESSAGES
from app.agent.providers.base import Message, Role
from app.core.errors import NotFoundError, ValidationError
from app.core.observability import get_logger
from app.db.models.conversation import ChatMode, Conversation, ConversationMessage, MessageRole
from app.db.models.task import TERMINAL_STATUSES, Run, Task, TaskStatus
from app.services.provider_service import AUTO_MODEL, ProviderService, split_model

log = get_logger(__name__)

MAX_CONVERSATIONS = 200
TITLE_CHARS = 60
UNSET = object()


@dataclass(slots=True)
class Turn:
    """The latest exchange's state, so the screen can resume a live run."""

    task_id: uuid.UUID
    status: TaskStatus
    run_id: uuid.UUID | None


def _title_from(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


class ConversationService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    # --- threads ---------------------------------------------------

    async def conversations(self) -> list[Conversation]:
        result = await self.session.scalars(
            select(Conversation)
            .where(Conversation.owner_id == self.owner_id)
            .order_by(Conversation.updated_at.desc())
            .limit(MAX_CONVERSATIONS)
        )
        return list(result.all())

    async def get(self, conversation_id: uuid.UUID) -> Conversation:
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.owner_id == self.owner_id
            )
        )
        if conversation is None:
            raise NotFoundError("No such conversation.")
        return conversation

    async def create(
        self,
        *,
        mode: ChatMode = ChatMode.GENERAL,
        model: str = AUTO_MODEL,
        team: bool = False,
    ) -> Conversation:
        conversation = Conversation(
            owner_id=self.owner_id,
            mode=mode,
            model=await self._check_model(model),
            team=team,
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def update(
        self,
        conversation_id: uuid.UUID,
        *,
        title: str | None = None,
        mode: ChatMode | None = None,
        model: str | None = None,
        team: bool | None = None,
    ) -> Conversation:
        """Any setting can change mid-conversation. Switching the model
        is the point: history is plain text, so the next reply simply
        comes from the new one."""
        conversation = await self.get(conversation_id)
        if title is not None:
            conversation.title = title.strip()[:200] or conversation.title
        if mode is not None:
            conversation.mode = mode
        if model is not None:
            conversation.model = await self._check_model(model)
        if team is not None:
            conversation.team = team
        # Set here rather than left to the database, so the value is
        # known without reloading the row.
        conversation.updated_at = datetime.now(UTC)
        return conversation

    async def delete(self, conversation_id: uuid.UUID) -> None:
        await self.session.delete(await self.get(conversation_id))

    async def messages(self, conversation_id: uuid.UUID) -> list[ConversationMessage]:
        await self.get(conversation_id)
        result = await self.session.scalars(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.owner_id == self.owner_id,
            )
            .order_by(ConversationMessage.created_at, ConversationMessage.role.desc())
        )
        return list(result.all())

    async def latest_turn(self, conversation_id: uuid.UUID) -> Turn | None:
        task = await self.session.scalar(
            select(Task)
            .where(Task.conversation_id == conversation_id, Task.owner_id == self.owner_id)
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        if task is None:
            return None
        run_id = await self.session.scalar(
            select(Run.id).where(Run.task_id == task.id).order_by(Run.attempt.desc()).limit(1)
        )
        return Turn(task_id=task.id, status=task.status, run_id=run_id)

    # --- sending ----------------------------------------------------

    async def send(
        self, conversation_id: uuid.UUID, *, text: str, user_id: uuid.UUID
    ) -> tuple[ConversationMessage, Task]:
        conversation = await self.get(conversation_id)
        text = text.strip()
        if not text:
            raise ValidationError("Write a message first.")

        turn = await self.latest_turn(conversation_id)
        if turn is not None and turn.status not in TERMINAL_STATUSES:
            # One answer at a time keeps the history in order.
            raise ValidationError("Wait for the current answer, or stop it, before sending more.")

        task = Task(
            owner_id=self.owner_id,
            conversation_id=conversation.id,
            title=_title_from(text),
            input=text,
            created_by=user_id,
        )
        self.session.add(task)
        await self.session.flush()

        message = ConversationMessage(
            owner_id=self.owner_id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=text,
            task_id=task.id,
            created_at=datetime.now(UTC),
        )
        self.session.add(message)
        if conversation.title == "New chat":
            conversation.title = _title_from(text)
        conversation.updated_at = datetime.now(UTC)
        await self.session.flush()
        log.info("chat_message_sent", conversation_id=str(conversation.id), task_id=str(task.id))
        return message, task

    # --- what the worker uses --------------------------------------

    async def history_before(self, task: Task) -> list[Message]:
        """Earlier turns, as plain text, newest kept when trimming.

        Failed replies are left out, so a model never reads an error
        message as something it said. Tool steps are not replayed: the
        answer that came out of them is what the conversation holds.
        """
        assert task.conversation_id is not None
        rows = (
            await self.session.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == task.conversation_id,
                    ConversationMessage.owner_id == self.owner_id,
                    ConversationMessage.error.is_(None),
                )
                .order_by(ConversationMessage.created_at.desc())
                .limit(HISTORY_MESSAGES + 2)
            )
        ).all()

        kept: list[Message] = []
        used = 0
        for row in rows:  # newest first
            if row.task_id == task.id:
                continue  # the message being answered now
            used += len(row.content)
            if used > HISTORY_CHARS or len(kept) >= HISTORY_MESSAGES:
                break
            role = Role.USER if row.role is MessageRole.USER else Role.ASSISTANT
            kept.append(Message(role=role, content=row.content))
        kept.reverse()
        # A history must not open with a reply to something it no longer contains.
        while kept and kept[0].role is Role.ASSISTANT:
            kept.pop(0)
        return kept

    async def record_reply(
        self,
        task: Task,
        *,
        content: str | None,
        model: str | None,
        error: str | None,
        tools_used: list[str] | None = None,
    ) -> ConversationMessage:
        assert task.conversation_id is not None
        reply = ConversationMessage(
            owner_id=self.owner_id,
            conversation_id=task.conversation_id,
            role=MessageRole.ASSISTANT,
            content=(content or "").strip() or ("" if error else "(No answer.)"),
            task_id=task.id,
            model=model,
            error=error,
            tools_used=tools_used or [],
            created_at=datetime.now(UTC),
        )
        self.session.add(reply)
        conversation = await self.session.get(Conversation, task.conversation_id)
        if conversation is not None:
            conversation.updated_at = datetime.now(UTC)
        await self.session.flush()
        return reply

    # --- checks -----------------------------------------------------

    async def _check_model(self, model: str) -> str:
        model = model.strip() or AUTO_MODEL
        if model == AUTO_MODEL:
            return model
        provider_key, name = split_model(model)
        connected = {
            c.provider_key for c in await ProviderService(self.session, self.owner_id).connected()
        }
        if provider_key not in connected or not name:
            raise ValidationError(
                "That AI is not connected. Connect it under AI Providers, or choose Automatic."
            )
        return f"{provider_key}:{name}"
