"""Model registry.

Every model must be imported here so Alembic autogenerate and the
tenant-isolation test can see it.
"""

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.identity import (
    Invitation,
    Membership,
    PlatformAdmin,
    PlatformAdminAudit,
    RefreshToken,
    Role,
    User,
)
from app.db.models.organization import Organization, OrgStatus

__all__ = [
    "Base",
    "Invitation",
    "Membership",
    "OrgStatus",
    "Organization",
    "PlatformAdmin",
    "PlatformAdminAudit",
    "RefreshToken",
    "Role",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
]
