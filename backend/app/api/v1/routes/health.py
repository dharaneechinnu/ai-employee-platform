"""Health endpoints.

Two endpoints, because "the process is running" and "the process can do
useful work" are different questions:

- /healthz  liveness.  Answers without touching anything. If this fails,
            restart the container.
- /readyz   readiness. Checks Postgres and Redis. If this fails, stop
            sending traffic here, but do not restart — the dependency is
            what is broken, not us.
"""

from typing import Literal

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.observability import get_logger
from app.db.session import get_session

log = get_logger(__name__)
router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str


class DependencyStatus(BaseModel):
    ok: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    database: DependencyStatus
    redis: DependencyStatus


@router.get("/healthz", response_model=LivenessResponse, summary="Liveness probe")
async def healthz(settings: Settings = Depends(get_settings)) -> LivenessResponse:
    return LivenessResponse(service=settings.app_name)


async def _check_database(session: AsyncSession) -> DependencyStatus:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - report any failure, never raise
        log.warning("readiness_database_failed", error=str(exc))
        return DependencyStatus(ok=False, detail=type(exc).__name__)
    return DependencyStatus(ok=True)


async def _check_redis(settings: Settings) -> DependencyStatus:
    client: aioredis.Redis = aioredis.Redis.from_url(str(settings.redis_url))
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        log.warning("readiness_redis_failed", error=str(exc))
        return DependencyStatus(ok=False, detail=type(exc).__name__)
    finally:
        await client.aclose()
    return DependencyStatus(ok=True)


@router.get("/readyz", response_model=ReadinessResponse, summary="Readiness probe")
async def readyz(
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ReadinessResponse:
    database = await _check_database(session)
    redis_status = await _check_redis(settings)

    ready = database.ok and redis_status.ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ready" if ready else "degraded",
        database=database,
        redis=redis_status,
    )
