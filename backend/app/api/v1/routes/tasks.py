"""Task and run routes, including the live stream.

A task is one turn of a conversation. These routes read them, cancel
them and stream a run's events; sending a message (which creates the
task and queues the job) lives with the conversation.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.api.v1.deps import ContextDep, SessionDep
from app.db.models.task import TERMINAL_STATUSES, RunStatus, TaskStatus
from app.db.session import get_sessionmaker
from app.services.live_feed import Cursor, LiveFeed
from app.services.task_service import TaskService

router = APIRouter(prefix="/me", tags=["tasks"])


# How often to send an SSE comment when nothing is happening. Without
# it, proxies and load balancers quietly drop an idle connection.
KEEPALIVE_SECONDS = 15
POLL_SECONDS = 0.5
# The account stream is long-lived and watched by an open tab, so it
# polls more gently, and ends after a while: the browser reconnects with
# where it was, which also keeps proxies from holding connections for ever.
ACCOUNT_POLL_SECONDS = 1.0
ACCOUNT_STREAM_SECONDS = 300


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: RunStatus
    step_count: int
    prompt_tokens: int
    output_tokens: int
    # Estimated: with BYOK we never see the provider's actual invoice.
    estimated_cost_usd: Decimal
    output: str | None
    stop_cause: str | None
    error_message: str | None
    started_at: datetime | None
    ended_at: datetime | None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    input: str
    status: TaskStatus
    dry_run: bool
    conversation_id: uuid.UUID
    created_at: datetime
    run: RunSummary | None = None


class TaskListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    status: TaskStatus
    conversation_id: uuid.UUID
    created_at: datetime


def _run_summary(run: Any) -> RunSummary | None:
    if run is None:
        return None
    return RunSummary(
        id=run.id,
        status=run.status,
        step_count=run.step_count,
        prompt_tokens=run.prompt_tokens,
        output_tokens=run.output_tokens,
        estimated_cost_usd=run.cost_usd,
        output=run.output,
        stop_cause=run.stop_cause,
        error_message=run.error_message,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )


@router.get("/tasks", response_model=list[TaskListItem], summary="List tasks")
async def list_tasks(
    ctx: ContextDep, session: SessionDep, limit: Annotated[int, Query(le=200)] = 50
) -> list[TaskListItem]:
    tasks = await TaskService(session, ctx.owner_id).list_tasks(limit=limit)
    return [TaskListItem.model_validate(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="Read one task")
async def get_task(task_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> TaskResponse:
    current = await TaskService(session, ctx.owner_id).get(task_id)
    response = TaskResponse.model_validate(current.task)
    response.run = _run_summary(current.run)
    return response


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse, summary="Cancel a task")
async def cancel_task(task_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> TaskResponse:
    service = TaskService(session, ctx.owner_id)
    # `get` is what enforces ownership: it returns None, and so 404s,
    # for a task belonging to anybody else.
    await service.get(task_id)

    task = await service.request_cancel(task_id)
    await session.commit()

    refreshed = await service.get(task_id)
    response = TaskResponse.model_validate(task)
    response.run = _run_summary(refreshed.run)
    return response


@router.get("/runs/{run_id}", response_model=RunSummary, summary="Read one run")
async def get_run(run_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> RunSummary:
    run = await TaskService(session, ctx.owner_id).get_run(run_id)
    summary = _run_summary(run)
    assert summary is not None
    return summary


@router.get("/runs/{run_id}/trace", summary="The full history of a run")
async def get_trace(
    run_id: uuid.UUID, ctx: ContextDep, session: SessionDep
) -> dict[str, list[dict[str, Any]]]:
    service = TaskService(session, ctx.owner_id)
    events = await service.events_after(run_id, 0)
    tools = await service.invocations(run_id)
    calls = await service.llm_calls(run_id)

    return {
        "events": [
            {"seq": e.seq, "type": e.type, "payload": e.payload, "at": e.created_at.isoformat()}
            for e in events
        ],
        "tool_invocations": [
            {"tool": t.tool_name, "ok": t.ok, "error_class": t.error_class} for t in tools
        ],
        "llm_calls": [
            {
                "model": c.model,
                "prompt_tokens": c.prompt_tokens,
                "output_tokens": c.output_tokens,
                "estimated_cost_usd": str(c.cost_usd),
            }
            for c in calls
        ],
    }


@router.get("/runs/{run_id}/events", summary="Live stream of a run (SSE)")
async def stream_events(
    run_id: uuid.UUID,
    ctx: ContextDep,
    session: SessionDep,
    request: Request,
    last_event_id: Annotated[int, Query(alias="last_event_id")] = 0,
) -> StreamingResponse:
    """Server-sent events.

    One direction only, which is all a run needs, so SSE rather than a
    WebSocket: simpler, plain HTTP, and reconnects natively.

    A client reconnecting sends the last `seq` it saw and receives
    everything after it, so a dropped connection loses nothing.
    """
    service = TaskService(session, ctx.owner_id)
    await service.get_run(run_id)  # 404s before the stream opens if not theirs

    async def generate() -> AsyncGenerator[str, None]:
        seq = last_event_id
        idle = 0.0

        while True:
            if await request.is_disconnected():
                break

            events = await service.events_after(run_id, seq)
            for event in events:
                seq = event.seq
                idle = 0.0
                payload = {"seq": event.seq, "type": event.type, **event.payload}
                yield (f"id: {event.seq}\nevent: {event.type}\ndata: {json.dumps(payload)}\n\n")

            run = await service.get_run(run_id)
            if run.status not in (RunStatus.RUNNING, RunStatus.AWAITING_APPROVAL) and not events:
                yield f"event: done\ndata: {json.dumps({'status': run.status.value})}\n\n"
                break

            await asyncio.sleep(POLL_SECONDS)
            idle += POLL_SECONDS
            if idle >= KEEPALIVE_SECONDS:
                idle = 0.0
                yield ": keepalive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/live", summary="Live stream of everything the account is doing (SSE)")
async def stream_account(
    ctx: ContextDep,
    request: Request,
    last_event_id: Annotated[str, Query()] = "",
    last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    max_seconds: Annotated[int, Query(ge=1, le=ACCOUNT_STREAM_SECONDS)] = ACCOUNT_STREAM_SECONDS,
) -> StreamingResponse:
    """Server-sent events for every run and every scheduler step of the
    signed-in person, in one stream, so the agent tree can show many
    agents working at once.

    Same sign-in as the per-run stream, and only the caller's own events
    are ever read. A new viewer sees what happens from now on; one
    reconnecting sends the position it last saw and receives the rest.
    Frames carry no `event:` name, so a plain `onmessage` gets them all;
    the kind is the `type` field.
    """
    owner_id = ctx.owner_id
    resume = Cursor.parse(last_event_id) or Cursor.parse(last_event_id_header)
    maker = get_sessionmaker()

    async def generate() -> AsyncGenerator[str, None]:
        # A short session per look, never one held open for minutes.
        async with maker() as session:
            cursor = resume or await LiveFeed(session, owner_id).now()
        yield ": connected\n\n"

        idle = 0.0
        ends_at = time.monotonic() + max_seconds
        while time.monotonic() < ends_at:
            if await request.is_disconnected():
                break
            async with maker() as session:
                events, cursor = await LiveFeed(session, owner_id).after(cursor)
            for i, event in enumerate(events):
                idle = 0.0
                # The position goes on the last frame only: a connection
                # lost halfway through a batch must resume from before it.
                mark = f"id: {cursor}\n" if i == len(events) - 1 else ""
                yield f"{mark}data: {json.dumps(event)}\n\n"
            if not events:
                await asyncio.sleep(ACCOUNT_POLL_SECONDS)
                idle += ACCOUNT_POLL_SECONDS
                if idle >= KEEPALIVE_SECONDS:
                    idle = 0.0
                    yield ": keepalive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


_ = TERMINAL_STATUSES  # referenced by the service layer
