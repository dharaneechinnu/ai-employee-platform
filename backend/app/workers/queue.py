"""Enqueueing work from the API side.

The API only ever puts a job on the queue; it never runs an agent.
"""

from __future__ import annotations

import uuid
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings
from app.core.observability import get_logger

log = get_logger(__name__)

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(str(get_settings().redis_url))


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None


async def enqueue_task(task_id: uuid.UUID) -> str | None:
    """Queue an agent run.

    The job id is the task id, so a duplicate submission of the same
    task cannot start two runs of it.
    """
    pool = await get_pool()
    job = await pool.enqueue_job("run_task", str(task_id), _job_id=f"run_task:{task_id}")
    if job is None:
        log.info("task_already_queued", task_id=str(task_id))
        return None
    return str(job.job_id)


async def enqueue(name: str, *args: Any, **kwargs: Any) -> str | None:
    pool = await get_pool()
    job = await pool.enqueue_job(name, *args, **kwargs)
    return str(job.job_id) if job else None
