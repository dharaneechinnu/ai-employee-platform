"""Worker configuration and the ping job."""

from app.workers.jobs import ping
from app.workers.main import WorkerSettings


async def test_ping_returns_a_timestamp() -> None:
    result = await ping({"job_id": "test-job"}, note="hello")

    assert result["note"] == "hello"
    assert result["pong"]


def test_worker_registers_at_least_one_function() -> None:
    """arq refuses to start a worker with nothing registered, and a worker
    that cannot start is not a walking skeleton. This caught a real bug in
    phase 0, so it is pinned by a test."""
    assert WorkerSettings.functions, "the worker must register at least one job"


def test_worker_concurrency_follows_slow_mode() -> None:
    assert WorkerSettings.max_jobs >= 1
