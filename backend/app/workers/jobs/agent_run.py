"""Run one task.

This is the slow half of the split: the API queued a row and answered
in milliseconds, and this does the work that takes minutes.

Every step is written to Postgres before being published to Redis, so
a dropped publish costs a live update but never a record.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent.loop import AgentEvent, AgentLoop, Budget, StopCause
from app.agent.providers import build_provider
from app.agent.tools.base import ToolContext
from app.agent.tools.registry import registry
from app.core.errors import NotFoundError
from app.core.observability import get_logger
from app.db.models.ai_employee import AIEmployee, AIEmployeeVersion
from app.db.models.task import LLMCall, Run, RunStatus, Task, TaskStatus
from app.db.session import get_sessionmaker
from app.schemas.ai_employee import EmployeeConfig
from app.services.employee_service import build_system_prompt
from app.services.provider_service import ProviderService
from app.services.task_service import EventWriter, estimate_cost

log = get_logger(__name__)

WORKER_ID = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"


async def run_task(ctx: dict[str, Any], task_id: str) -> dict[str, Any]:
    maker = get_sessionmaker()
    return await _execute(maker, uuid.UUID(task_id))


async def _execute(maker: async_sessionmaker, task_id: uuid.UUID) -> dict[str, Any]:  # type: ignore[type-arg]
    async with maker() as session:
        task = await session.scalar(select(Task).where(Task.id == task_id))
        if task is None:
            log.warning("run_task_missing", task_id=str(task_id))
            return {"status": "missing"}

        if task.status not in (TaskStatus.QUEUED,):
            # Already picked up, cancelled, or finished. Re-delivery is
            # normal with a queue, so this is a no-op rather than an error.
            return {"status": str(task.status)}

        employee = await session.get(AIEmployee, task.employee_id)
        version = await session.get(AIEmployeeVersion, task.employee_version_id)
        if employee is None or version is None:  # pragma: no cover
            task.status = TaskStatus.FAILED
            await session.commit()
            return {"status": "failed", "reason": "configuration missing"}

        config = EmployeeConfig.model_validate(version.config)

        run = Run(
            org_id=task.org_id,
            task_id=task.id,
            attempt=1,
            status=RunStatus.RUNNING,
            started_at=datetime.now(UTC),
            heartbeat_at=datetime.now(UTC),
            worker_id=WORKER_ID,
        )
        session.add(run)
        task.status = TaskStatus.RUNNING
        await session.flush()
        await session.commit()

    # A fresh session for the run itself: the agent loop can take
    # minutes, and holding a connection open that long starves the pool.
    async with maker() as session:
        run_db = await session.get(Run, run.id)
        assert run_db is not None
        writer = EventWriter(session, run_db.id, task.org_id)

        provider_key, model = _split_model(config.model)
        try:
            api_key = await ProviderService(session, task.org_id).resolve_api_key(provider_key)
        except NotFoundError:
            # No key connected. A clear message beats a mysterious
            # failure three steps into a run.
            await writer.append("run_stopped", {"cause": "provider_not_connected"})
            return await _finish(
                session,
                run_db,
                task_id,
                RunStatus.FAILED,
                stop_cause="provider_not_connected",
                error=(
                    f"No API key is connected for '{provider_key}'. "
                    "Connect one in Settings before running tasks."
                ),
            )

        async def sink(event: AgentEvent) -> None:
            await writer.append(event.type, event.payload)
            run_db.heartbeat_at = datetime.now(UTC)
            await session.commit()

        async def cancelled() -> bool:
            fresh = await session.scalar(select(Task.cancel_requested).where(Task.id == task_id))
            return bool(fresh)

        loop = AgentLoop(
            provider=build_provider(provider_key, api_key),
            model=model,
            tools=registry.for_employee(config.enabled_tools),
            tool_context=ToolContext(org_id=task.org_id, run_id=run_db.id, dry_run=task.dry_run),
            budget=Budget(max_steps=config.max_steps),
            temperature=config.temperature,
            on_event=sink,
            is_cancelled=cancelled,
        )

        outcome = await loop.run(
            system_prompt=build_system_prompt(
                config, name=employee.name, job_title=employee.job_title
            ),
            task=task.input,
        )

        cost = estimate_cost(provider_key, model, outcome.prompt_tokens, outcome.output_tokens)
        session.add(
            LLMCall(
                run_id=run_db.id,
                org_id=task.org_id,
                provider_key=provider_key,
                model=model,
                prompt_tokens=outcome.prompt_tokens,
                output_tokens=outcome.output_tokens,
                cost_usd=cost,
                created_at=datetime.now(UTC),
            )
        )

        run_db.step_count = outcome.steps
        run_db.prompt_tokens = outcome.prompt_tokens
        run_db.output_tokens = outcome.output_tokens
        run_db.cost_usd = cost
        run_db.output = outcome.output

        status = {
            StopCause.COMPLETED: RunStatus.COMPLETED,
            StopCause.CANCELLED: RunStatus.CANCELLED,
        }.get(outcome.stop_cause, RunStatus.FAILED)

        return await _finish(
            session,
            run_db,
            task_id,
            status,
            stop_cause=outcome.stop_cause,
            error=None if status is RunStatus.COMPLETED else outcome.output,
        )


async def _finish(
    session: Any,
    run: Run,
    task_id: uuid.UUID,
    status: RunStatus,
    *,
    stop_cause: str,
    error: str | None,
) -> dict[str, Any]:
    run.status = status
    run.stop_cause = stop_cause
    run.error_message = (error or None) if status is not RunStatus.COMPLETED else None
    run.ended_at = datetime.now(UTC)

    task = await session.get(Task, task_id)
    if task is not None:
        task.status = {
            RunStatus.COMPLETED: TaskStatus.COMPLETED,
            RunStatus.CANCELLED: TaskStatus.CANCELLED,
        }.get(status, TaskStatus.FAILED)

    await session.commit()
    log.info("run_finished", run_id=str(run.id), status=str(status), cause=stop_cause)
    return {"status": str(status), "stop_cause": stop_cause, "run_id": str(run.id)}


def _split_model(model: str) -> tuple[str, str]:
    """Accept "gemini:gemini-2.0-flash" or a bare model name.

    A bare name defaults to Gemini, which is the documented starting
    provider, so existing configuration keeps working.
    """
    if ":" in model:
        provider_key, _, name = model.partition(":")
        return provider_key, name
    return "gemini", model
