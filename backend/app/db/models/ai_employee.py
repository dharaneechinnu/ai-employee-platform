"""AI Employees: the configurable workers a company builds.

The important shape here is versioning. `ai_employees` holds identity
and status; every save writes an immutable snapshot of the settings to
`ai_employee_versions`. Tasks (phase 4) point at a *version*, not the
employee, so "what instructions did it have last Tuesday?" stays
answerable after any later edit.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, StrEnumType, TimestampMixin, UUIDPrimaryKeyMixin


class EmployeeStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


# Archived employees do not count toward a company's limit: archiving is
# how you free a slot without losing the history of what that employee did.
COUNTS_TOWARD_LIMIT = (EmployeeStatus.DRAFT, EmployeeStatus.ACTIVE, EmployeeStatus.PAUSED)


class AIEmployee(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_employees"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(100))
    avatar: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[EmployeeStatus] = mapped_column(
        StrEnumType(EmployeeStatus, 20), nullable=False, default=EmployeeStatus.DRAFT
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_ai_employees_org_status", "org_id", "status"),)

    def __repr__(self) -> str:
        return f"<AIEmployee {self.name} ({self.status})>"


class AIEmployeeVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An immutable snapshot of one employee's settings.

    Stored as a whole JSON blob rather than a diff against the previous
    version: reading version 3 must never require replaying versions 1
    and 2. Storage is cheap; correctness under audit is not.
    """

    __tablename__ = "ai_employee_versions"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_employees.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("employee_id", "version_no", name="uq_employee_version_no"),
        Index("ix_ai_employee_versions_employee", "employee_id"),
    )


class Template(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A ready-made starting point.

    `org_id` NULL means a platform template, visible to everyone.
    `org_id` set means that company's own template, visible only inside
    it — a company template may encode private business rules, so it
    must never become visible to other customers.
    """

    __tablename__ = "templates"

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    department: Mapped[str | None] = mapped_column(String(100))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (Index("ix_templates_org_id", "org_id"),)
