"""The History list and one run's detail, for the signed-in person.

Everything is built from rows a run already leaves behind: the run, its
task, the model calls and the event log. Every query filters on the
owner, and a run that is not theirs is a 404, the same as for the run
routes.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import exists, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.pricing import plan_of
from app.core.errors import NotFoundError, ValidationError
from app.db.models.agent import Agent
from app.db.models.task import LLMCall, Run, RunEvent, RunStatus, Task

SUMMARY_CHARS = 160
MAX_LANES = 40


@dataclass(slots=True)
class HistoryFilter:
    agent_id: uuid.UUID | None = None
    status: RunStatus | None = None
    trigger: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    model: str | None = None
    # "free": nothing was charged. "paid": something was.
    cost: str | None = None
    q: str | None = None


@dataclass(slots=True)
class ModelUsed:
    provider_key: str
    model: str
    plan: str
    prompt_tokens: int
    output_tokens: int
    cost_usd: Decimal


@dataclass(slots=True)
class Lane:
    kind: str  # "agent", "specialist" or "tool"
    label: str
    # The tool's name or the specialist's role, for a nicer label on screen.
    key: str
    start_ms: int
    end_ms: int
    ok: bool | None = None


@dataclass(slots=True)
class HistoryRow:
    run: Run
    task: Task
    agent_name: str | None
    agent_archived: bool
    models: list[ModelUsed] = field(default_factory=list)

    @property
    def duration_seconds(self) -> int | None:
        if self.run.started_at is None:
            return None
        end = self.run.ended_at or datetime.now(UTC)
        return max(0, int((end - self.run.started_at).total_seconds()))

    @property
    def summary(self) -> str:
        run = self.run
        text = run.error_message if run.status is RunStatus.FAILED else run.output
        for line in (text or "").splitlines():
            line = line.strip().lstrip("#*- ").strip()
            if line:
                return line[:SUMMARY_CHARS]
        return (self.task.title or "")[:SUMMARY_CHARS]


def encode_cursor(run: Run) -> str:
    raw = f"{run.created_at.isoformat()}|{run.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        when, _, ident = raw.partition("|")
        return datetime.fromisoformat(when), uuid.UUID(ident)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationError("That page marker is not valid.") from exc


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class HistoryService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    async def list_runs(
        self, filters: HistoryFilter, *, limit: int, cursor: str | None
    ) -> tuple[list[HistoryRow], str | None]:
        """Newest first. The second value is the marker for the next page,
        or None when there is nothing older."""
        query = (
            select(Run, Task, Agent.name, Agent.archived)
            .join(Task, Task.id == Run.task_id)
            .outerjoin(Agent, Agent.id == Run.agent_id)
            .where(Run.owner_id == self.owner_id)
        )
        f = filters
        if f.agent_id is not None:
            query = query.where(Run.agent_id == f.agent_id)
        if f.status is not None:
            query = query.where(Run.status == f.status)
        if f.trigger is not None:
            query = query.where(Run.trigger == f.trigger)
        if f.since is not None:
            query = query.where(Run.created_at >= f.since)
        if f.until is not None:
            query = query.where(Run.created_at < f.until)
        if f.model:
            query = query.where(exists().where(LLMCall.run_id == Run.id, LLMCall.model == f.model))
        if f.cost == "free":
            query = query.where(Run.cost_usd == 0)
        elif f.cost == "paid":
            query = query.where(Run.cost_usd > 0)
        if f.q and f.q.strip():
            like = _like(f.q.strip())
            query = query.where(
                or_(
                    Task.title.ilike(like, escape="\\"),
                    Run.output.ilike(like, escape="\\"),
                    Run.error_message.ilike(like, escape="\\"),
                    Agent.name.ilike(like, escape="\\"),
                )
            )
        if cursor:
            when, ident = decode_cursor(cursor)
            query = query.where(tuple_(Run.created_at, Run.id) < tuple_(when, ident))

        # One extra row tells us whether there is another page.
        found = (
            await self.session.execute(
                query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit + 1)
            )
        ).all()
        more = len(found) > limit
        rows = [
            HistoryRow(run=r, task=t, agent_name=name, agent_archived=bool(archived))
            for r, t, name, archived in found[:limit]
        ]
        used = await self._models([row.run.id for row in rows])
        for row in rows:
            row.models = used.get(row.run.id, [])
        return rows, (encode_cursor(rows[-1].run) if more and rows else None)

    async def models_seen(self) -> list[str]:
        """Every model any of the person's runs has used, for the filter."""
        result = await self.session.scalars(
            select(LLMCall.model)
            .where(LLMCall.owner_id == self.owner_id)
            .group_by(LLMCall.model)
            .order_by(func.max(LLMCall.created_at).desc())
        )
        return list(result.all())

    async def get(self, run_id: uuid.UUID) -> tuple[HistoryRow, list[Lane]]:
        found = (
            await self.session.execute(
                select(Run, Task, Agent.name, Agent.archived)
                .join(Task, Task.id == Run.task_id)
                .outerjoin(Agent, Agent.id == Run.agent_id)
                .where(Run.id == run_id, Run.owner_id == self.owner_id)
            )
        ).first()
        if found is None:
            raise NotFoundError("No such run.")
        run, task, name, archived = found
        row = HistoryRow(run=run, task=task, agent_name=name, agent_archived=bool(archived))
        row.models = (await self._models([run.id])).get(run.id, [])
        events = (
            await self.session.scalars(
                select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)
            )
        ).all()
        return row, build_lanes(row, list(events))

    async def _models(self, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ModelUsed]]:
        if not run_ids:
            return {}
        calls = (
            await self.session.scalars(
                select(LLMCall).where(LLMCall.run_id.in_(run_ids)).order_by(LLMCall.created_at)
            )
        ).all()
        merged: dict[uuid.UUID, dict[tuple[str, str], ModelUsed]] = {}
        for c in calls:
            slot = merged.setdefault(c.run_id, {})
            used = slot.setdefault(
                (c.provider_key, c.model), ModelUsed(c.provider_key, c.model, "", 0, 0, Decimal(0))
            )
            used.prompt_tokens += c.prompt_tokens
            used.output_tokens += c.output_tokens
            used.cost_usd += c.cost_usd
        for slot in merged.values():
            for used in slot.values():
                used.plan = plan_of(used.provider_key, used.model, used.cost_usd)
        return {run_id: list(slot.values()) for run_id, slot in merged.items()}


def _label(tool: str) -> str:
    text = tool.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def build_lanes(row: HistoryRow, events: list[RunEvent]) -> list[Lane]:
    """Who did what, over time, as offsets from the start of the run.

    The first lane is the whole run (the agent, or the assistant). Each
    tool call runs from its `tool_call` event to the next `tool_result`
    for the same tool, and each specialist from `specialist_started` to
    its finish. A call with no end yet (a run waiting for approval, or
    one still going) runs to the end of the run.
    """
    run = row.run
    origin = run.started_at or (events[0].created_at if events else run.created_at)

    def at(when: datetime) -> int:
        return max(0, int((when - origin).total_seconds() * 1000))

    total = max([at(run.ended_at) if run.ended_at else 0, *(at(e.created_at) for e in events)])

    lanes = [Lane("agent", row.agent_name or "Assistant", "", 0, total)]
    open_tools: dict[str, list[Lane]] = {}
    open_specialists: dict[str, Lane] = {}
    for e in events:
        if len(lanes) >= MAX_LANES:
            break
        p = e.payload
        tool = str(p.get("tool"))
        if e.type == "tool_call" and p.get("tool"):
            lane = Lane("tool", _label(tool), tool, at(e.created_at), total)
            open_tools.setdefault(tool, []).append(lane)
            lanes.append(lane)
        elif e.type == "tool_result" and open_tools.get(tool):
            lane = open_tools[tool].pop(0)
            lane.end_ms, lane.ok = at(e.created_at), bool(p.get("ok", True))
        elif e.type == "specialist_started":
            role = str(p.get("role", "specialist"))
            lane = Lane("specialist", _label(role), role, at(e.created_at), total)
            open_specialists[str(p.get("id"))] = lane
            lanes.append(lane)
        elif e.type in ("specialist_finished", "specialist_failed"):
            ended = open_specialists.pop(str(p.get("id")), None)
            if ended is not None:
                ended.end_ms = at(e.created_at)
                ended.ok = e.type == "specialist_finished" and bool(p.get("ok", True))
    return lanes
