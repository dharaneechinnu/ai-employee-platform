"""Per-company notification settings.

A run that pauses for approval is only useful if someone notices. These
settings decide who hears about it, and where: email to the people
concerned, and optionally a Slack channel.

The Slack webhook URL is a secret (anyone holding it can post to the
channel), so it is stored like every other credential: encrypted,
write-only, shown back only as its last four characters.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NotificationSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notification_settings"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    slack_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    slack_webhook_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    slack_webhook_last4: Mapped[str | None] = mapped_column(String(8))

    # Which events are worth interrupting someone for.
    on_approval_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    on_task_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    on_task_failed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
