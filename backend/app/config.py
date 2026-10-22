"""Application settings, loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder, not a credential: Settings rejects it when ENVIRONMENT=prod.
# At least 32 bytes: below that, HMAC-SHA256 is weaker than the hash it
# is built on (RFC 7518 section 3.2), and PyJWT rightly warns about it.
DEV_JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"  # noqa: S105
DEV_ENCRYPTION_KEY = "dev-only-insecure-encryption-key-change-me"


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

    # Master key for envelope encryption of secrets at rest.
    encryption_key: str = DEV_ENCRYPTION_KEY

    # --- public addresses ------------------------------------------
    # Where people reach the app and the API. Used to build OAuth
    # redirect URIs and the links in notification messages.
    public_app_url: str = "http://localhost:5173"
    public_api_url: str = "http://localhost:8000"

    # Lets a company's own AI server or MCP tool server live on a
    # private address or plain http. Local development only: in
    # production it would let anyone make our servers call internal
    # addresses.
    allow_private_urls: bool = False

    # --- one-click connections (OAuth) -------------------------------
    # Register one OAuth app per provider for the whole platform. Each
    # company then connects its own account through it; tokens are
    # stored per company, encrypted like provider keys.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    microsoft_client_id: str | None = None
    microsoft_client_secret: str | None = None
    # "common" accepts work, school and personal Microsoft accounts.
    microsoft_tenant: str = "common"

    # --- web search ----------------------------------------------------
    # One search service for the whole platform (Brave Search API).
    # Unset means the web_search tool says it is not set up, and an agent
    # that needs it is told so before it is created.
    brave_api_key: str | None = None

    # --- outgoing email (notifications) ------------------------------
    # Unset means email notifications are unavailable; Slack still works.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_ssl: bool = False  # True for port 465; otherwise STARTTLS

    # --- worker -------------------------------------------------------
    # One job at a time by default: a single agent task makes 10-15 model
    # calls, so two concurrent tasks will exceed a free-tier rate limit.
    # See HLD part 2 and LLD part 8.
    slow_mode: bool = True

    # Team mode as a supervisor graph (router, helpers side by side, review
    # loop) instead of the lead calling `ask_specialist` itself. Off until it
    # has been tried with a real model.
    agent_supervisor: bool = False

    # Run chats as a LangGraph graph whose approval pauses are saved in
    # Postgres (`GraphLoop`), instead of the snapshot in `run_checkpoints`.
    # Runs already paused under the old way still resume the old way.
    agent_checkpointer: bool = False
    worker_max_jobs: int = 10

    @property
    def effective_worker_concurrency(self) -> int:
        return 1 if self.slow_mode else self.worker_max_jobs

    @property
    def email_notifications_available(self) -> bool:
        return bool(self.smtp_host and (self.smtp_from or self.smtp_username))

    @property
    def is_testing(self) -> bool:
        return self.environment == "test"

    @model_validator(mode="after")
    def _reject_dev_secret_in_prod(self) -> "Settings":
        """A forgotten secret in production is a total auth bypass: anyone
        who reads this repository could mint a valid token. Fail at
        startup rather than serve traffic."""
        if self.environment == "prod":
            if self.jwt_secret == DEV_JWT_SECRET:
                raise ValueError("JWT_SECRET must be set to a real value in production")
            if self.encryption_key == DEV_ENCRYPTION_KEY:
                raise ValueError("ENCRYPTION_KEY must be set to a real value in production")
            if self.allow_private_urls:
                raise ValueError("ALLOW_PRIVATE_URLS is for local development only")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
