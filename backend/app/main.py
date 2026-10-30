"""FastAPI application factory.

This process serves HTTP only. It never runs an agent — that is the
worker's job. See HLD part 2.3.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import (
    agents,
    approval_links,
    auth,
    connections,
    conversations,
    health,
    history,
    memory,
    notifications,
    platform,
    policies,
    providers,
    setup,
    speech,
    tasks,
    usage,
)
from app.config import Settings, get_settings
from app.core.error_handlers import register_error_handlers
from app.core.observability import configure_logging, get_logger
from app.db.session import dispose_engine
from app.workers.queue import close_pool

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
    await close_pool()
    await dispose_engine()
    log.info("api_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.debug, json_logs=settings.environment != "dev")

    # The interactive API docs list every route and schema: useful while
    # building, needless surface in production.
    show_docs = settings.environment != "prod"
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if show_docs else None,
        redoc_url="/redoc" if show_docs else None,
        openapi_url="/openapi.json" if show_docs else None,
        lifespan=lifespan,
    )

    # CORS only for the Vite dev server. In production the web server
    # serves the app and proxies /api on the same origin, so the browser
    # never makes a cross-origin call.
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
    app.include_router(providers.router, prefix=settings.api_v1_prefix)
    app.include_router(policies.router, prefix=settings.api_v1_prefix)
    app.include_router(memory.router, prefix=settings.api_v1_prefix)
    app.include_router(tasks.router, prefix=settings.api_v1_prefix)
    app.include_router(platform.router, prefix=settings.api_v1_prefix)
    app.include_router(connections.router, prefix=settings.api_v1_prefix)
    app.include_router(connections.callback_router, prefix=settings.api_v1_prefix)
    app.include_router(notifications.router, prefix=settings.api_v1_prefix)
    app.include_router(approval_links.router, prefix=settings.api_v1_prefix)
    app.include_router(speech.router, prefix=settings.api_v1_prefix)
    app.include_router(agents.router, prefix=settings.api_v1_prefix)
    app.include_router(conversations.router, prefix=settings.api_v1_prefix)
    app.include_router(setup.router, prefix=settings.api_v1_prefix)
    app.include_router(history.router, prefix=settings.api_v1_prefix)
    app.include_router(usage.router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
