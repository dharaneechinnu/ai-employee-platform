"""Task and run routes, including the live stream.

`POST /tasks` must answer in milliseconds. It writes a row, queues a
job and returns; the worker does the slow part. Anything else means
browser timeouts and lost work.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.deps import RequestContext, SessionDep, require_permission
from app.core.errors import PermissionDeniedError
from app.core.permissions import Permission
from app.db.models.task import TERMINAL_STATUSES, RunStatus, TaskStatus
from app.services.task_service import TaskService
from app.workers.queue import enqueue_task

router = APIRouter(prefix="/orgs/{org_id}", tags=["tasks"])

CanRead = Annotated[RequestContext, Depends(require_permission(Permission.TASK_READ))]
CanCreate = Annotated[RequestContext, Depends(require_permission(Permission.TASK_CREATE))]

# How often to send an SSE comment when nothing is happening. Without
# it, proxies and load balancers quietly drop an idle connection.
KEEPALIVE_SECONDS = 15
POLL_SECONDS = 0.5


class CreateTaskRequest(BaseModel):
    employee_id: uuid.UUID
    input: str = Field(min_length=1, max_length=10_000)
    title: str | None = Field(default=None, max_length=200)
    dry_run: bool = False


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
    employee_id: uuid.UUID
    created_at: datetime
    run: RunSummary | None = None


class TaskListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    status: TaskStatus
    employee_id: uuid.UUID
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


@router.post(
    "/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Assign a task (returns immediately)",
)
async def create_task(body: CreateTaskRequest, ctx: CanCreate, session: SessionDep) -> TaskResponse:
    task = await TaskService(session, ctx.org_id).create(
        employee_id=body.employee_id,
        text=body.input,
        title=body.title,
        dry_run=body.dry_run,
        user_id=ctx.user_id,
    )
    # Commit before queueing: a worker must never pick up a job whose
    # row is not visible yet.
    await session.commit()
    await enqueue_task(task.id)

    return TaskResponse.model_validate(task)


@router.get("/tasks", response_model=list[TaskListItem], summary="List tasks")
async def list_tasks(
    ctx: CanRead, session: SessionDep, limit: Annotated[int, Query(le=200)] = 50
) -> list[TaskListItem]:
    tasks = await TaskService(session, ctx.org_id).list_tasks(limit=limit)
    return [TaskListItem.model_validate(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="Read one task")
async def get_task(task_id: uuid.UUID, ctx: CanRead, session: SessionDep) -> TaskResponse:
    current = await TaskService(session, ctx.org_id).get(task_id)
    response = TaskResponse.model_validate(current.task)
    response.run = _run_summary(current.run)
    return response


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse, summary="Cancel a task")
async def cancel_task(task_id: uuid.UUID, ctx: CanRead, session: SessionDep) -> TaskResponse:
    service = TaskService(session, ctx.org_id)
    current = await service.get(task_id)

    # A Member may stop their own work, not someone else's.
    if current.task.created_by != ctx.user_id and not ctx.can(Permission.TASK_CANCEL_ANY):
        raise PermissionDeniedError("You can only cancel tasks you started.")

    task = await service.request_cancel(task_id)
    await session.commit()

    refreshed = await service.get(task_id)
    response = TaskResponse.model_validate(task)
    response.run = _run_summary(refreshed.run)
    return response


@router.get("/runs/{run_id}", response_model=RunSummary, summary="Read one run")
async def get_run(run_id: uuid.UUID, ctx: CanRead, session: SessionDep) -> RunSummary:
    run = await TaskService(session, ctx.org_id).get_run(run_id)
    summary = _run_summary(run)
    assert summary is not None
    return summary


@router.get("/runs/{run_id}/trace", summary="The full history of a run")
async def get_trace(
    run_id: uuid.UUID, ctx: CanRead, session: SessionDep
) -> dict[str, list[dict[str, Any]]]:
    service = TaskService(session, ctx.org_id)
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
    ctx: CanRead,
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
    service = TaskService(session, ctx.org_id)
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


_ = TERMINAL_STATUSES  # referenced by the service layer
