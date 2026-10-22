"""Model registry.

Every model must be imported here so Alembic autogenerate and the
tenant-isolation test can see it.
"""

from app.db.models.agent import Agent
from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.checkpoint import GraphCheckpoint, GraphCheckpointWrite
from app.db.models.conversation import ChatMode, Conversation, ConversationMessage, MessageRole
from app.db.models.identity import (
    PlatformAdmin,
    PlatformAdminAudit,
    RefreshToken,
    SetupToken,
    User,
)
from app.db.models.mcp import McpServer
from app.db.models.memory import (
    VECTOR_TABLES,
    EmbeddingConfig,
    Memory,
    MemoryKind,
    MemoryVector384,
    MemoryVector768,
    MemoryVector1024,
    MemoryVector1536,
    ReembedJob,
    RunSummary,
)
from app.db.models.notification import NotificationSettings
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
    OrgOAuthApp,
    OrgServiceAccess,
    PlatformOAuthApp,
    PlatformServiceAccess,
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
    "Agent",
    "Approval",
    "ApprovalStatus",
    "Base",
    "ChatMode",
    "Connection",
    "ConnectionKind",
    "ConnectionStatus",
    "Conversation",
    "ConversationMessage",
    "EmbeddingConfig",
    "EventType",
    "GraphCheckpoint",
    "GraphCheckpointWrite",
    "LLMCall",
    "McpServer",
    "Memory",
    "MemoryKind",
    "MemoryVector384",
    "MemoryVector768",
    "MemoryVector1024",
    "MemoryVector1536",
    "MessageRole",
    "NotificationSettings",
    "OrgConnectionAccess",
    "OrgOAuthApp",
    "OrgServiceAccess",
    "PlatformAdmin",
    "PlatformAdminAudit",
    "PlatformOAuthApp",
    "PlatformServiceAccess",
    "Policy",
    "PolicyDefault",
    "PolicyScope",
    "PolicySetting",
    "ProviderConfig",
    "ProviderKind",
    "ReembedJob",
    "RefreshToken",
    "Run",
    "RunCheckpoint",
    "RunEvent",
    "RunStatus",
    "RunSummary",
    "SetupToken",
    "SupportedProvider",
    "Task",
    "TaskStatus",
    "TimestampMixin",
    "ToolInvocation",
    "UUIDPrimaryKeyMixin",
    "User",
]
