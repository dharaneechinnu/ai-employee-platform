"""Setup progress: which first-time steps a person has finished.

The progress bar and the provider guides read this, so a step that is
done stays done after logout and on another device. Steps are ticked by
what the app can see (a key that tested fine, an app that is connected),
never by a click, and a tick is never taken back: deleting a key later
does not send someone back to step one.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SetupProgress(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "setup_progress"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # step id -> when it was first seen done (ISO 8601, UTC).
    steps: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    # provider key -> guide step ids already done, in the order they were finished.
    guide: Mapped[dict[str, list[str]]] = mapped_column(JSONB, nullable=False, default=dict)
