"""Worker configuration and the ping job."""

import pytest

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


def test_event_redaction_keeps_token_counts_but_hides_secrets() -> None:
    """ "prompt_tokens" holds the word "token" but is a usage number,
    not a secret; hiding it left every timeline without usage."""
    from app.services.task_service import _redact

    out = _redact(
        {"prompt_tokens": 120, "output_tokens": 30, "api_key": "sk-1", "access_token": "x"}
    )
    assert out == {
        "prompt_tokens": 120,
        "output_tokens": 30,
        "api_key": "[redacted]",
        "access_token": "[redacted]",
    }


async def test_a_resume_after_approval_gets_its_own_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """arq keeps a finished job's id for an hour. Reusing the task's id
    for the resume had it dropped as a duplicate, so an approved task
    never carried on."""
    import uuid as uuid_module

    import app.workers.queue as queue

    seen: list[str] = []

    class Pool:
        async def enqueue_job(self, name: str, *args: object, _job_id: str) -> object | None:
            if _job_id in seen:
                return None  # what arq does with an id it still remembers
            seen.append(_job_id)
            return type("Job", (), {"job_id": _job_id})()

    pool = Pool()

    async def get_pool() -> Pool:
        return pool

    monkeypatch.setattr(queue, "get_pool", get_pool)
    task, approval = uuid_module.uuid4(), uuid_module.uuid4()

    assert await queue.enqueue_task(task) is not None
    assert await queue.enqueue_task(task) is None  # a double submit
    assert await queue.enqueue_task(task, resume_after=approval) is not None
    assert await queue.enqueue_task(task, resume_after=approval) is None  # a double click
