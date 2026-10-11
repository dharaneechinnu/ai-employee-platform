"""Organization — one customer company. The tenant boundary."""

from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class OrgStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)

    status: Mapped[OrgStatus] = mapped_column(
        Enum(OrgStatus, name="org_status", native_enum=False, length=20),
        nullable=False,
        default=OrgStatus.ACTIVE,
        server_default=text("'active'"),
    )

    # How many AI Employees this company may create. Set by the Platform
    # Admin; enforced in the backend when an employee is created (phase 2).
    max_employees: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )

    __table_args__ = (
        CheckConstraint("max_employees >= 0", name="ck_organizations_max_employees_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug} ({self.status.value})>"
