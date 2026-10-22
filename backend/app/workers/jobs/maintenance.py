"""Scheduled housekeeping."""

from __future__ import annotations

from typing import Any

from app.agent.checkpoint import purge_stale
from app.core.observability import get_logger
from app.db.session import get_sessionmaker
from app.services.approval_service import expire_stale_approvals

log = get_logger(__name__)


async def expire_approvals(ctx: dict[str, Any]) -> int:
    """Fail runs whose approval nobody answered in time.

    Without this sweep a forgotten request holds its run open for ever,
    and an approval link in someone's inbox would still look live.
    """
    async with get_sessionmaker()() as session:
        expired = await expire_stale_approvals(session)
        purged = await purge_stale(session)
        await session.commit()
    if purged:
        log.info("checkpoints_purged", count=purged)
    if expired:
        log.info("approvals_expired", count=expired)
    return expired
