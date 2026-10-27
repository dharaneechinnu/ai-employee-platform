"""Setup progress: what a person has finished, detected from real data.

A step is ticked when the app can see proof of it, and a tick is saved
so it never goes backwards. The status endpoint is read on every page
load, so detection is four cheap existence checks and a write only when
something new was seen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.policy import Connection
from app.db.models.provider import ConnectionStatus, ProviderConfig
from app.db.models.setup import SetupProgress
from app.db.models.task import Run

# In the order the person meets them. The bar shows the first undone one.
STEPS: tuple[str, ...] = ("pick_ai", "add_key", "connect_app", "first_agent")


@dataclass(slots=True)
class SetupStatus:
    done: list[str]
    next_step: str | None
    guide: dict[str, list[str]]

    @property
    def complete(self) -> bool:
        return self.next_step is None


class SetupService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    async def _row(self) -> SetupProgress:
        row = await self.session.scalar(
            select(SetupProgress).where(SetupProgress.owner_id == self.owner_id)
        )
        if row is None:
            row = SetupProgress(owner_id=self.owner_id, steps={}, guide={})
            self.session.add(row)
        return row

    async def _seen(self) -> set[str]:
        """Steps the data proves right now."""
        owner = self.owner_id
        checks = {
            "pick_ai": exists().where(ProviderConfig.owner_id == owner),
            "add_key": exists().where(
                ProviderConfig.owner_id == owner,
                ProviderConfig.status == ConnectionStatus.WORKING,
            ),
            "connect_app": exists().where(Connection.owner_id == owner),
            # Making an agent or running anything both count: either way
            # the person is past "what is this thing".
            "first_agent": exists().where(Agent.owner_id == owner)
            | exists().where(Run.owner_id == owner),
        }
        seen: set[str] = set()
        for step, clause in checks.items():
            if await self.session.scalar(select(clause)):
                seen.add(step)
        return seen

    async def status(self) -> SetupStatus:
        row = await self._row()
        seen = await self._seen()
        # A later step proves the earlier ones: a working key means an
        # AI was picked even if the row that said so was since replaced.
        for i, step in enumerate(STEPS):
            if step in seen:
                seen.update(STEPS[:i])
        new = [s for s in STEPS if s in seen and s not in row.steps]
        if new:
            now = datetime.now(UTC).isoformat()
            # Reassign rather than mutate: JSONB columns do not track
            # in-place changes, so the write would silently not happen.
            row.steps = {**row.steps, **dict.fromkeys(new, now)}
            await self.session.flush()
        done = [s for s in STEPS if s in row.steps]
        next_step = next((s for s in STEPS if s not in row.steps), None)
        return SetupStatus(done=done, next_step=next_step, guide=dict(row.guide))

    async def mark_guide_step(self, provider: str, step: str) -> SetupStatus:
        row = await self._row()
        done = list(row.guide.get(provider, []))
        if step not in done:
            done.append(step)
            row.guide = {**row.guide, provider: done}
            await self.session.flush()
        return await self.status()
