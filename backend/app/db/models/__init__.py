"""Model registry.

Every model must be imported here so Alembic autogenerate and the
owner-scoping test can see it.
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
from app.db.models.memory import (
    VECTOR_TABLES,
    EmbeddingConfig,
    Memory,
    MemoryKind,
    MemoryVector384,
    MemoryVector768,
    MemoryVector1024,
    MemoryVector1536,
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
    PersonConnectionAccess,
    PersonOAuthApp,
    PersonServiceAccess,
    PlatformConnectionAccess,
    PlatformOAuthApp,
    PlatformServiceAccess,
    ProviderConfig,
    ProviderKind,
    SupportedProvider,
)
from app.db.models.setup import SetupProgress
from app.db.models.task import (
    EventType,
    LLMCall,
    Run,
    RunEvent,
    RunStatus,
    SchedulerEvent,
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
    "Memory",
    "MemoryKind",
    "MemoryVector384",
    "MemoryVector768",
    "MemoryVector1024",
    "MemoryVector1536",
    "MessageRole",
    "NotificationSettings",
    "PersonConnectionAccess",
    "PersonOAuthApp",
    "PersonServiceAccess",
    "PlatformAdmin",
    "PlatformAdminAudit",
    "PlatformConnectionAccess",
    "PlatformOAuthApp",
    "PlatformServiceAccess",
    "Policy",
    "PolicyDefault",
    "PolicyScope",
    "PolicySetting",
    "ProviderConfig",
    "ProviderKind",
    "RefreshToken",
    "Run",
    "RunCheckpoint",
    "RunEvent",
    "RunStatus",
    "RunSummary",
    "SchedulerEvent",
    "SetupProgress",
    "SetupToken",
    "SupportedProvider",
    "Task",
    "TaskStatus",
    "TimestampMixin",
    "ToolInvocation",
    "UUIDPrimaryKeyMixin",
    "User",
]
