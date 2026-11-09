"""Settings behaviour."""

from app.config import Settings


def test_slow_mode_forces_single_concurrency() -> None:
    """One agent task makes 10-15 model calls. Running two at once is what
    trips a free-tier rate limit first, so slow_mode pins concurrency to 1."""
    settings = Settings(slow_mode=True, worker_max_jobs=10)
    assert settings.effective_worker_concurrency == 1


def test_disabling_slow_mode_uses_configured_concurrency() -> None:
    settings = Settings(slow_mode=False, worker_max_jobs=10)
    assert settings.effective_worker_concurrency == 10


def test_the_stalled_run_time_has_a_safe_default() -> None:
    assert Settings().run_stall_seconds == 600


def test_a_stalled_run_time_that_would_end_healthy_runs_is_refused() -> None:
    """Zero or a negative number would end every running run on each sweep, and
    a few seconds would end runs that are only waiting on a slow model."""
    import pytest
    from pydantic import ValidationError

    for bad in (-1, 0, 30, 119):
        with pytest.raises(ValidationError):
            Settings(run_stall_seconds=bad)
    assert Settings(run_stall_seconds=120).run_stall_seconds == 120
