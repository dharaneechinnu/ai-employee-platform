"""Worker entrypoint.

This process runs background jobs. It never serves HTTP — that is the
API's job. See HLD part 2.3.

In phase 0 there are no jobs yet; this exists so the split process model
is real from the start rather than retrofitted.
"""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.config import get_settings
from app.core.observability import configure_logging, get_logger

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

    functions: ClassVar[list[Any]] = []  # phase 4 registers run_task here
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
