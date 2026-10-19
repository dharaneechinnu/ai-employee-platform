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
from app.db.models.mcp import McpServer
from app.db.models.memory import (
    VECTOR_TABLES,
    EmbeddingConfig,
    Memory,
    MemoryKind,
    MemoryScope,
    MemoryVector384,
    MemoryVector768,
    MemoryVector1024,
    MemoryVector1536,
    ReembedJob,
    RunSummary,
)
from app.db.models.notification import NotificationSettings
from app.db.models.organization import Organization, OrgStatus
from app.db.models.policy import (
    Approval,
    ApprovalStatus,
    Connection,
    ConnectionKind,
    Policy,
    PolicyDefault,
    PolicyScope,
    PolicySetting,
    RunCheckpoint,
)
from app.db.models.provider import (
    ConnectionStatus,
    OrgConnectionAccess,
    PlatformOAuthApp,
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
    "VECTOR_TABLES",
    "AIEmployee",
    "AIEmployeeVersion",
    "Approval",
    "ApprovalStatus",
    "Base",
    "Connection",
    "ConnectionKind",
    "ConnectionStatus",
    "EmbeddingConfig",
    "EmployeeStatus",
    "EventType",
    "Invitation",
    "LLMCall",
    "McpServer",
    "Membership",
    "Memory",
    "MemoryKind",
    "MemoryScope",
    "MemoryVector384",
    "MemoryVector768",
    "MemoryVector1024",
    "MemoryVector1536",
    "NotificationSettings",
    "OrgConnectionAccess",
    "OrgStatus",
    "Organization",
    "PlatformAdmin",
    "PlatformAdminAudit",
    "PlatformOAuthApp",
    "Policy",
    "PolicyDefault",
    "PolicyScope",
    "PolicySetting",
    "ProviderConfig",
    "ProviderKind",
    "ReembedJob",
    "RefreshToken",
    "Role",
    "Run",
    "RunCheckpoint",
    "RunEvent",
    "RunStatus",
    "RunSummary",
    "SupportedProvider",
    "Task",
    "TaskStatus",
    "Template",
    "TimestampMixin",
    "ToolInvocation",
    "UUIDPrimaryKeyMixin",
    "User",
]
