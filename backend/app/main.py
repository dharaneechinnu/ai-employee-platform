"""FastAPI application factory.

This process serves HTTP only. It never runs an agent — that is the
worker's job. See HLD part 2.3.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import (
    ai_employees,
    auth,
    health,
    orgs,
    platform,
    policies,
    providers,
    tasks,
)
from app.config import Settings, get_settings
from app.core.error_handlers import register_error_handlers
from app.core.observability import configure_logging, get_logger
from app.db.session import dispose_engine

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings: Settings = get_settings()
    log.info(
        "api_starting",
        environment=settings.environment,
        slow_mode=settings.slow_mode,
    )
    yield
    await dispose_engine()
    log.info("api_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.debug, json_logs=settings.environment != "dev")

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Dev-only permissive CORS. Phase 1 replaces this with an explicit
    # origin list once real auth cookies are in play.
    if settings.environment == "dev":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_error_handlers(app)

    # Health probes sit at the root so orchestrators do not need to
    # know the API version.
    app.include_router(health.router)

    app.include_router(auth.router, prefix=settings.api_v1_prefix)
    app.include_router(orgs.router, prefix=settings.api_v1_prefix)
    app.include_router(ai_employees.router, prefix=settings.api_v1_prefix)
    app.include_router(providers.router, prefix=settings.api_v1_prefix)
    app.include_router(policies.router, prefix=settings.api_v1_prefix)
    app.include_router(tasks.router, prefix=settings.api_v1_prefix)
    app.include_router(platform.router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
