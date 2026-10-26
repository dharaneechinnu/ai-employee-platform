"""Declarative base, shared column mixins, and the enum column type."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, String, TypeDecorator, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """All models inherit from this.

    The owner-scoping test (tests/isolation/) walks every mapper
    registered here and fails if a table is missing ``owner_id`` and is not
    on the explicit global-table whitelist.
    """


class StrEnumType(TypeDecorator[Any]):
    """Store a StrEnum as VARCHAR and load it back as the enum.

    Declaring ``Mapped[SomeEnum] = mapped_column(String(20))`` is a
    trap: SQLAlchemy stores the value happily but hands back a plain
    ``str``. Equality keeps working, because StrEnum subclasses str, so
    the mistake stays hidden until something calls ``.value``, which
    raises, or uses ``is``, which silently returns False for ever. The
    second shape is the dangerous one: a guard written as
    ``if status is not Status.PENDING`` then fires on every call.

    The column stays a plain VARCHAR, so no migration is needed. Only
    the Python side changes, and it becomes honest.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_class: type[StrEnum], length: int = 30) -> None:
        super().__init__(length=length)
        self.enum_class = enum_class

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return str(self.enum_class(value))

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return self.enum_class(value)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        # Also set in the database, so rows inserted by raw SQL (fixtures,
        # data migrations, psql) still get a valid id.
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
