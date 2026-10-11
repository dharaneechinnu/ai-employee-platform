"""Application settings, loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---------------------------------------------------------
    app_name: str = "AI Employee Platform"
    environment: Literal["dev", "test", "prod"] = "dev"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # --- infrastructure ----------------------------------------------
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://app:app@localhost:5432/ai_employee"),
    )
    redis_url: RedisDsn = Field(default=RedisDsn("redis://localhost:6379/0"))

    # --- database pool -----------------------------------------------
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_echo: bool = False

    # --- worker -------------------------------------------------------
    # One job at a time by default: a single agent task makes 10-15 model
    # calls, so two concurrent tasks will exceed a free-tier rate limit.
    # See HLD part 2 and LLD part 8.
    slow_mode: bool = True
    worker_max_jobs: int = 10

    @property
    def effective_worker_concurrency(self) -> int:
        return 1 if self.slow_mode else self.worker_max_jobs

    @property
    def is_testing(self) -> bool:
        return self.environment == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
