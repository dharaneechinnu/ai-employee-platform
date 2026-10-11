"""Repository base classes.

Every query in the application goes through a repository. No route and no
service builds a `select()` itself.

The reason is `org_id`. Filtering happens in exactly one place here, so
"can company A read company B's data?" is a single-file audit rather than
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
    """For tables that are not tenant-scoped (users, platform admins)."""

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


class OrgScopedRepository[ModelT: Base](BaseRepository[ModelT]):
    """For every table that holds customer data.

    Two safety properties:

    - `_scoped()` is the only entry point for building a query, and it
      always applies the `org_id` filter.
    - `create()` sets `org_id` itself, so a caller cannot pass another
      company's id even by accident.
    """

    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        super().__init__(session)
        self.org_id = org_id

    @property
    def _org_column(self) -> Any:
        # Guaranteed present: the tenant-isolation test fails CI for any
        # model used here that lacks org_id.
        return self.model.__table__.c.org_id

    def _scoped(self) -> Select[Any]:
        return select(self.model).where(self._org_column == self.org_id)

    async def get(self, id_: uuid.UUID) -> ModelT | None:
        """Returns None both when the row is absent and when it belongs to
        another company. Callers turn None into 404 — never 403 — so the
        existence of another company's data is never revealed."""
        stmt = self._scoped().where(self.model.__table__.c.id == id_)
        return cast("ModelT | None", await self.session.scalar(stmt))

    async def list(self) -> Sequence[ModelT]:
        result = await self.session.scalars(self._scoped())
        return cast("Sequence[ModelT]", result.all())

    async def count(self) -> int:
        stmt = select(func.count()).select_from(self.model).where(self._org_column == self.org_id)
        return (await self.session.scalar(stmt)) or 0

    def create(self, **data: Any) -> ModelT:
        data.pop("org_id", None)  # never trust a caller-supplied org_id
        instance = self.model(org_id=self.org_id, **data)
        self.session.add(instance)
        return instance
