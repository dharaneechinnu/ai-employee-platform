"""Worker entrypoint.

This process runs background jobs. It never serves HTTP — that is the
API's job. See HLD part 2.3.

Phase 0 registers only `ping`, which exists to prove the queue path
works end to end and to keep the two-process split real from the start
rather than retrofitted later.
"""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.config import get_settings
from app.core.observability import configure_logging, get_logger
from app.workers.jobs import ping

log = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(debug=settings.debug, json_logs=settings.environment != "dev")
    log.info("worker_starting", concurrency=settings.effective_worker_concurrency)


async def shutdown(ctx: dict[str, Any]) -> None:
    from app.db.session import dispose_engine

    await dispose_engine()
    log.info("worker_stopped")


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(str(get_settings().redis_url))


class WorkerSettings:
    """arq looks for this class by name."""

    # arq refuses to start with nothing registered, and a worker that
    # cannot start is not a walking skeleton. `ping` also proves the
    # API -> Redis -> worker path, which is the half that matters.
    functions: ClassVar[list[Any]] = [ping]  # phase 4 adds run_task
    cron_jobs: ClassVar[list[Any]] = []  # phase 5 registers expire_approvals, phase 8 the reaper

    on_startup = startup
    on_shutdown = shutdown

    redis_settings = _redis_settings()

    # One job at a time while slow_mode is on. A single agent task makes
    # 10-15 model calls, so concurrency here is what trips free-tier
    # rate limits first.
    max_jobs = get_settings().effective_worker_concurrency
    job_timeout = 900
    keep_result = 3600
