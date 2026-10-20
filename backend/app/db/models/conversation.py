"""Conversations: the personal assistant, ChatGPT-style.

A conversation is a thread of messages with one person. Each thing the
person sends becomes an ordinary task (with `conversation_id` set and
no AI Employee), so a chat turn gets everything a task already has:
the agent loop with tools, live streaming, approvals, cancel, cost and
the full run record. Only the persona and the history differ.

The model is a setting of the conversation, not of each message, and it
can change at any time: history is stored as plain text, so a thread
started on Gemini carries on with Claude or a local Llama unchanged.
Each reply records which model wrote it.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, StrEnumType, TimestampMixin, UUIDPrimaryKeyMixin


class ChatMode(StrEnum):
    GENERAL = "general"
    STUDY = "study"
    WORK = "work"
    RESEARCH = "research"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New chat")
    mode: Mapped[ChatMode] = mapped_column(
        StrEnumType(ChatMode, 20), nullable=False, default=ChatMode.GENERAL
    )
    # "auto" or "provider:model", exactly as an AI Employee's model.
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="auto")
    # Orchestration: the assistant may split the work between
    # specialists (researcher, analyst, writer, critic) and combine it.
    team: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Tool names this conversation may use, as the tool picker stores them.
    tools: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (Index("ix_conversations_owner_updated", "owner_id", "updated_at"),)


class ConversationMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversation_messages"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(StrEnumType(MessageRole, 20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # The turn this message belongs to: the user's message and the
    # reply to it share one task, which links to the run's full record.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL")
    )
    # On a reply: which model wrote it ("anthropic:claude-opus-5-5").
    model: Mapped[str | None] = mapped_column(String(200))
    # On a reply that did not finish: what went wrong, said plainly.
    # Kept out of later history, so a failure is not repeated as fact.
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_conversation_messages_conversation", "conversation_id", "created_at"),
        Index("ix_conversation_messages_owner", "owner_id"),
    )
