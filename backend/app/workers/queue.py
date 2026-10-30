"""Enqueueing work from the API side.

The API only ever puts a job on the queue; it never runs an agent.
"""

from __future__ import annotations

import uuid

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


async def enqueue_task(task_id: uuid.UUID, *, resume_after: uuid.UUID | None = None) -> str | None:
    """Queue an agent run.

    The job id is the task id, so a duplicate submission of the same
    task cannot start two runs of it.

    A resume after an approval needs its own id (`resume_after`, the
    approval). arq keeps a finished job's id for an hour, so reusing the
    task id would have the resume silently dropped as a duplicate and
    the approved task would wait for ever. Keyed by the approval, a
    double click on Approve still queues it only once.
    """
    pool = await get_pool()
    job_id = f"run_task:{task_id}" + (f":resume:{resume_after}" if resume_after else "")
    job = await pool.enqueue_job("run_task", str(task_id), _job_id=job_id)
    if job is None:
        log.info("task_already_queued", task_id=str(task_id))
        return None
    return str(job.job_id)
