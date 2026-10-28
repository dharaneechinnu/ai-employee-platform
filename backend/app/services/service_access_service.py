"""Level 1 of service permissions: what the platform allows, for everyone
and for one person.

Reads and writes the two rule tables. A per-person ruling beats the
platform's (a Platform Admin can open Sheets for one pilot account while
it is off for everyone else); no ruling at either level means allowed,
so introducing this changed nothing for anyone already connected.

Editing includes looking: if a service's `read` is closed, its `edit`
is closed too, whatever its own rule says.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.services import EDIT, LEVELS, READ, SERVICES
from app.core.errors import ValidationError
from app.db.models.provider import PersonServiceAccess, PlatformServiceAccess


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    # "person", "platform" or "default": who made the call, so a
    # refusal can say who to ask.
    source: str
    note: str | None = None


def _check(service: str, level: str) -> None:
    if service not in SERVICES:
        raise ValidationError(f"Unknown service '{service}'.")
    if level not in LEVELS:
        raise ValidationError("Level must be 'read' or 'edit'.")


class ServiceAccessService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID | None = None) -> None:
        self.session = session
        self.owner_id = owner_id

    # --- reading -----------------------------------------------------

    async def _platform(self) -> dict[tuple[str, str], bool]:
        rows = await self.session.scalars(select(PlatformServiceAccess))
        return {(r.service, r.level): r.allowed for r in rows.all()}

    async def _person(self, owner_id: uuid.UUID) -> dict[tuple[str, str], PersonServiceAccess]:
        rows = await self.session.scalars(
            select(PersonServiceAccess).where(PersonServiceAccess.owner_id == owner_id)
        )
        return {(r.service, r.level): r for r in rows.all()}

    async def snapshot(self) -> Snapshot:
        """Everything needed to decide, loaded once for a whole check."""
        assert self.owner_id is not None
        return Snapshot(await self._platform(), await self._person(self.owner_id))

    async def decide(self, service: str, level: str) -> Decision:
        return (await self.snapshot()).decide(service, level)

    # --- Platform Admin: platform-wide ---------------------------------

    async def platform_matrix(self) -> dict[tuple[str, str], bool]:
        platform = await self._platform()
        return {
            (sid, level): platform.get((sid, level), True)
            for sid, svc in SERVICES.items()
            for level in LEVELS
            if level == READ or svc.has_edit
        }

    async def set_platform(
        self, service: str, level: str, allowed: bool, *, admin_id: uuid.UUID | None
    ) -> None:
        _check(service, level)
        row = await self.session.scalar(
            select(PlatformServiceAccess).where(
                PlatformServiceAccess.service == service, PlatformServiceAccess.level == level
            )
        )
        if row is None:
            self.session.add(
                PlatformServiceAccess(
                    service=service, level=level, allowed=allowed, updated_by=admin_id
                )
            )
        else:
            row.allowed, row.updated_by = allowed, admin_id
        await self.session.flush()

    # --- Platform Admin: one person ------------------------------------

    async def set_person(
        self,
        owner_id: uuid.UUID,
        service: str,
        level: str,
        allowed: bool | None,
        *,
        note: str | None,
        admin_id: uuid.UUID | None,
    ) -> None:
        """`allowed=None` removes the ruling, so the person inherits again."""
        _check(service, level)
        if allowed is None:
            await self.session.execute(
                delete(PersonServiceAccess).where(
                    PersonServiceAccess.owner_id == owner_id,
                    PersonServiceAccess.service == service,
                    PersonServiceAccess.level == level,
                )
            )
            await self.session.flush()
            return
        row = (await self._person(owner_id)).get((service, level))
        if row is None:
            self.session.add(
                PersonServiceAccess(
                    owner_id=owner_id,
                    service=service,
                    level=level,
                    allowed=allowed,
                    note=(note or None) and note[:300],
                    updated_by=admin_id,
                )
            )
        else:
            row.allowed = allowed
            row.note = (note or None) and note[:300]
            row.updated_by = admin_id
        await self.session.flush()


@dataclass(frozen=True, slots=True)
class Snapshot:
    platform: dict[tuple[str, str], bool]
    person: dict[tuple[str, str], PersonServiceAccess]

    def _rule(self, service: str, level: str) -> Decision:
        if (ruling := self.person.get((service, level))) is not None:
            return Decision(ruling.allowed, "person", ruling.note)
        if (service, level) in self.platform:
            return Decision(self.platform[(service, level)], "platform")
        return Decision(True, "default")

    def decide(self, service: str, level: str) -> Decision:
        own = self._rule(service, level)
        if level == EDIT and own.allowed:
            looking = self._rule(service, READ)
            if not looking.allowed:
                return looking
        return own
