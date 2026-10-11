"""A trivial job, used to prove the queue path end to end.

Two reasons this exists in phase 0:

1. arq refuses to start a worker with no registered functions, so the
   process needs at least one.
2. It makes the walking skeleton complete. Without it we could show
   "the API talks to Postgres" but not "the API hands work to the worker
   and the worker picks it up" — which is the harder half, and the half
   every later phase depends on.

Phase 4 replaces this as the main path with `run_task`; `ping` stays as
a cheap liveness probe for the worker itself.
"""

from datetime import UTC, datetime
from typing import Any

from app.core.observability import get_logger

log = get_logger(__name__)


async def ping(ctx: dict[str, Any], note: str = "") -> dict[str, str]:
    """Return the time the worker processed this job."""
    processed_at = datetime.now(UTC).isoformat()
    log.info("worker_ping", job_id=ctx.get("job_id"), note=note, processed_at=processed_at)
    return {"pong": processed_at, "note": note}
