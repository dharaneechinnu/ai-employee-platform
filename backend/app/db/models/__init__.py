"""Model registry.

Every model must be imported here so Alembic autogenerate and the
tenant-isolation test can see it.
"""

from app.db.models.ai_employee import (
    AIEmployee,
    AIEmployeeVersion,
    EmployeeStatus,
    Template,
)
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
from app.db.models.provider import (
    ConnectionStatus,
    ProviderConfig,
    ProviderKind,
    SupportedProvider,
)
from app.db.models.task import (
    EventType,
    LLMCall,
    Run,
    RunEvent,
    RunStatus,
    Task,
    TaskStatus,
    ToolInvocation,
)

__all__ = [
    "AIEmployee",
    "AIEmployeeVersion",
    "Base",
    "ConnectionStatus",
    "EmployeeStatus",
    "EventType",
    "Invitation",
    "LLMCall",
    "Membership",
    "OrgStatus",
    "Organization",
    "PlatformAdmin",
    "PlatformAdminAudit",
    "ProviderConfig",
    "ProviderKind",
    "RefreshToken",
    "Role",
    "Run",
    "RunEvent",
    "RunStatus",
    "SupportedProvider",
    "Task",
    "TaskStatus",
    "Template",
    "TimestampMixin",
    "ToolInvocation",
    "UUIDPrimaryKeyMixin",
    "User",
]
