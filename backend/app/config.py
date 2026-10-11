"""Application settings, loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder, not a credential: Settings rejects it when ENVIRONMENT=prod.
# At least 32 bytes: below that, HMAC-SHA256 is weaker than the hash it
# is built on (RFC 7518 section 3.2), and PyJWT rightly warns about it.
DEV_JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"  # noqa: S105


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

    # --- auth ---------------------------------------------------------
    # Dev default only. The validator below refuses to start in prod
    # with this value still in place.
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    invite_expiry_hours: int = 72

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

    @model_validator(mode="after")
    def _reject_dev_secret_in_prod(self) -> "Settings":
        """A forgotten secret in production is a total auth bypass: anyone
        who reads this repository could mint a valid token. Fail at
        startup rather than serve traffic."""
        if self.environment == "prod" and self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET must be set to a real value in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
