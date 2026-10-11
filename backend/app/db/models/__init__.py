"""Model registry.

Every model must be imported here so Alembic autogenerate and the
tenant-isolation test can see it.
"""

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.organization import Organization, OrgStatus

__all__ = [
    "Base",
    "OrgStatus",
    "Organization",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
