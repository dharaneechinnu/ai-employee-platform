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


def test_is_testing_flag() -> None:
    assert Settings(environment="test").is_testing is True
    assert Settings(environment="dev").is_testing is False
