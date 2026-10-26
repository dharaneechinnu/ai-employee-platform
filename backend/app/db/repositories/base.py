"""Repository base classes.

Every query in the application goes through a repository. No route and no
service builds a `select()` itself.

The reason is `owner_id`. Filtering happens in exactly one place here, so
"can person A read person B's data?" is a single-file audit rather than
a review of every query in the codebase.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.base import Base


class BaseRepository[ModelT: Base]:
    """For tables that are not owner-scoped (users, platform admins)."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, id_)

    def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        return instance

    async def flush(self) -> None:
        await self.session.flush()


class OwnerScopedRepository[ModelT: Base](BaseRepository[ModelT]):
    """For every table that holds a person's own data.

    Two safety properties:

    - `_scoped()` is the only entry point for building a query, and it
      always applies the `owner_id` filter.
    - `create()` sets `owner_id` itself, so a caller cannot pass
      someone else's id even by accident.

    One scope column on every table, filtered in one place, is what
    keeps "can one person read another's data?" a single-file audit
    rather than a sweep of every query.
    """

    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        super().__init__(session)
        self.owner_id = owner_id

    @property
    def _owner_column(self) -> Any:
        # Guaranteed present: the isolation test fails CI for any model
        # used here that lacks owner_id.
        return self.model.__table__.c.owner_id

    def _scoped(self) -> Select[Any]:
        return select(self.model).where(self._owner_column == self.owner_id)

    async def get(self, id_: uuid.UUID) -> ModelT | None:
        """Returns None both when the row is absent and when it belongs
        to somebody else. Callers turn None into 404 — never 403 — so
        the existence of another person's data is never revealed."""
        stmt = self._scoped().where(self.model.__table__.c.id == id_)
        return cast("ModelT | None", await self.session.scalar(stmt))

    async def list(self) -> Sequence[ModelT]:
        result = await self.session.scalars(self._scoped())
        return cast("Sequence[ModelT]", result.all())

    async def count(self) -> int:
        stmt = (
            select(func.count()).select_from(self.model).where(self._owner_column == self.owner_id)
        )
        return (await self.session.scalar(stmt)) or 0

    def create(self, **data: Any) -> ModelT:
        data.pop("owner_id", None)  # never trust a caller-supplied owner_id
        instance = self.model(owner_id=self.owner_id, **data)
        self.session.add(instance)
        return instance
