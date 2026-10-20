"""The personal assistant: conversations, ChatGPT-style, on the agent loop.

A message is answered by a task, so the live run, approvals and cancel
use the routes that already exist for tasks and runs; these routes add
the threads themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from app.agent.assistant import MODES
from app.agent.team import ROLES
from app.api.v1.deps import ContextDep, SessionDep
from app.db.models.conversation import ChatMode, Conversation, MessageRole
from app.db.models.task import TaskStatus
from app.services.conversation_service import ConversationService
from app.workers.queue import enqueue_task

router = APIRouter(prefix="/me", tags=["assistant"])


class ModeInfo(BaseModel):
    key: ChatMode
    label: str
    for_whom: str
    examples: list[str]


class RoleInfo(BaseModel):
    key: str
    label: str


class AssistantInfo(BaseModel):
    modes: list[ModeInfo]
    team_roles: list[RoleInfo]


class ConversationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    mode: ChatMode
    model: str
    team: bool
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    task_id: uuid.UUID | None
    model: str | None
    error: str | None
    tools_used: list[str] = []
    created_at: datetime


class TurnResponse(BaseModel):
    task_id: uuid.UUID
    status: TaskStatus
    run_id: uuid.UUID | None


class ConversationResponse(ConversationItem):
    messages: list[MessageResponse] = []
    # The latest exchange, so a page opened mid-answer can follow it live.
    turn: TurnResponse | None = None


class CreateConversationRequest(BaseModel):
    mode: ChatMode = ChatMode.GENERAL
    model: str = Field(default="auto", max_length=200)
    team: bool = False


class UpdateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    mode: ChatMode | None = None
    model: str | None = Field(default=None, max_length=200)
    team: bool | None = None


class SendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class SendResponse(BaseModel):
    message: MessageResponse
    task_id: uuid.UUID


async def _full(service: ConversationService, conversation: Conversation) -> ConversationResponse:
    response = ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        mode=conversation.mode,
        model=conversation.model,
        team=conversation.team,
        updated_at=conversation.updated_at,
        messages=[
            MessageResponse.model_validate(m) for m in await service.messages(conversation.id)
        ],
    )
    turn = await service.latest_turn(conversation.id)
    if turn is not None:
        response.turn = TurnResponse(task_id=turn.task_id, status=turn.status, run_id=turn.run_id)
    return response


@router.get("/assistant", response_model=AssistantInfo, summary="Modes and team roles")
async def assistant_info(ctx: ContextDep) -> AssistantInfo:
    return AssistantInfo(
        modes=[
            ModeInfo(
                key=m.key,
                label=m.label,
                for_whom=m.for_whom,
                examples=list(m.examples),
            )
            for m in MODES.values()
        ],
        team_roles=[RoleInfo(key=r.key, label=r.label) for r in ROLES.values()],
    )


@router.get("/conversations", response_model=list[ConversationItem], summary="My conversations")
async def list_conversations(ctx: ContextDep, session: SessionDep) -> list[ConversationItem]:
    items = await ConversationService(session, ctx.owner_id).conversations()
    return [ConversationItem.model_validate(c) for c in items]


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation",
)
async def create_conversation(
    body: CreateConversationRequest, ctx: ContextDep, session: SessionDep
) -> ConversationResponse:
    service = ConversationService(session, ctx.owner_id)
    conversation = await service.create(mode=body.mode, model=body.model, team=body.team)
    await session.commit()
    return await _full(service, conversation)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    summary="A conversation with its messages",
)
async def get_conversation(
    conversation_id: uuid.UUID, ctx: ContextDep, session: SessionDep
) -> ConversationResponse:
    service = ConversationService(session, ctx.owner_id)
    return await _full(service, await service.get(conversation_id))


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    summary="Rename, or change the mode, model or team",
)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: UpdateConversationRequest,
    ctx: ContextDep,
    session: SessionDep,
) -> ConversationResponse:
    service = ConversationService(session, ctx.owner_id)
    conversation = await service.update(
        conversation_id,
        title=body.title,
        mode=body.mode,
        model=body.model,
        team=body.team,
    )
    await session.commit()
    return await _full(service, conversation)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation and its runs",
)
async def delete_conversation(
    conversation_id: uuid.UUID, ctx: ContextDep, session: SessionDep
) -> None:
    await ConversationService(session, ctx.owner_id).delete(conversation_id)
    await session.commit()


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SendResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a message (the answer streams from its run)",
)
async def send_message(
    conversation_id: uuid.UUID, body: SendRequest, ctx: ContextDep, session: SessionDep
) -> SendResponse:
    message, task = await ConversationService(session, ctx.owner_id).send(
        conversation_id, text=body.content, user_id=ctx.user_id
    )
    # Commit before queueing: a worker must never pick up a job whose
    # row is not visible yet.
    await session.commit()
    await enqueue_task(task.id)
    return SendResponse(message=MessageResponse.model_validate(message), task_id=task.id)
