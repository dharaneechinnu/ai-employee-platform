"""History: every run the signed-in person has had, newest first.

The list is paged with a marker (`next`) rather than a page number, so a
run that finishes while someone is scrolling never shifts the page under
them. One run's detail adds what the side panel needs: the lanes (who did
what over time), the models used and the result. Replaying a run step by
step uses the run's existing event stream.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.v1.deps import ContextDep, SessionDep
from app.db.models.task import RunStatus
from app.services.history_service import (
    HistoryFilter,
    HistoryRow,
    HistoryService,
    Lane,
    ModelUsed,
)

router = APIRouter(prefix="/me/history", tags=["history"])


class ModelUsedOut(BaseModel):
    provider_key: str
    model: str
    # "free", "paid" or "unknown" (no price on file for it).
    plan: str
    prompt_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal


class HistoryItem(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    conversation_id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None
    title: str | None
    summary: str
    status: RunStatus
    # "chat", "schedule" or "manual".
    trigger: str
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    duration_seconds: int | None
    estimated_cost_usd: Decimal
    models: list[ModelUsedOut]


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    # Pass back as `before` for older runs; null when there are none.
    next: str | None


class LaneOut(BaseModel):
    kind: str
    label: str
    key: str
    start_ms: int
    end_ms: int
    ok: bool | None


class HistoryDetail(HistoryItem):
    result: str | None
    error_message: str | None
    stop_cause: str | None
    step_count: int
    prompt_tokens: int
    output_tokens: int
    lanes: list[LaneOut]
    # "Run again" only makes sense for a run of an agent that still exists.
    can_run_again: bool


def _model(m: ModelUsed) -> ModelUsedOut:
    return ModelUsedOut(
        provider_key=m.provider_key,
        model=m.model,
        plan=m.plan,
        prompt_tokens=m.prompt_tokens,
        output_tokens=m.output_tokens,
        estimated_cost_usd=m.cost_usd,
    )


def _item(row: HistoryRow) -> dict[str, object]:
    run = row.run
    return {
        "id": run.id,
        "task_id": run.task_id,
        "conversation_id": row.task.conversation_id,
        "agent_id": run.agent_id,
        "agent_name": row.agent_name,
        "title": row.task.title,
        "summary": row.summary,
        "status": run.status,
        "trigger": run.trigger,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "created_at": run.created_at,
        "duration_seconds": row.duration_seconds,
        "estimated_cost_usd": run.cost_usd,
        "models": [_model(m) for m in row.models],
    }


@router.get("/runs", response_model=HistoryPage, summary="List past runs")
async def list_runs(
    ctx: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    before: Annotated[str | None, Query(description="The `next` marker of the last page.")] = None,
    agent_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
    trigger: Literal["chat", "schedule", "manual"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    model: Annotated[str | None, Query(max_length=100)] = None,
    cost: Literal["free", "paid"] | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> HistoryPage:
    filters = HistoryFilter(
        agent_id=agent_id,
        status=status,
        trigger=trigger,
        since=since,
        until=until,
        model=model,
        cost=cost,
        q=q,
    )
    rows, next_marker = await HistoryService(session, ctx.owner_id).list_runs(
        filters, limit=limit, cursor=before
    )
    return HistoryPage(items=[HistoryItem(**_item(r)) for r in rows], next=next_marker)


@router.get("/models", response_model=list[str], summary="Models used in past runs")
async def models_used(ctx: ContextDep, session: SessionDep) -> list[str]:
    return await HistoryService(session, ctx.owner_id).models_seen()


@router.get("/runs/{run_id}", response_model=HistoryDetail, summary="One past run in full")
async def get_run(run_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> HistoryDetail:
    row, lanes = await HistoryService(session, ctx.owner_id).get(run_id)
    run = row.run
    return HistoryDetail(
        **_item(row),
        result=run.output,
        error_message=run.error_message,
        stop_cause=run.stop_cause,
        step_count=run.step_count,
        prompt_tokens=run.prompt_tokens,
        output_tokens=run.output_tokens,
        lanes=[_lane(lane) for lane in lanes],
        can_run_again=run.agent_id is not None and not row.agent_archived,
    )


def _lane(lane: Lane) -> LaneOut:
    return LaneOut(
        kind=lane.kind,
        label=lane.label,
        key=lane.key,
        start_ms=lane.start_ms,
        end_ms=lane.end_ms,
        ok=lane.ok,
    )
