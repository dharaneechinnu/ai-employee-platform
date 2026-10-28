"""an everyone-level on/off for each kind of app

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-28 12:00:00.000000

`platform_connection_access` holds one row per kind of app (mailbox,
GitHub, PostgreSQL, Slack, Teams, Google, Microsoft) that a Platform
Admin has switched on or off for everyone. No row means allowed, so
nothing changes for anyone until a row is written. A person's own
ruling in `org_connection_access` still beats it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.text("now()")
UUID_PK = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "platform_connection_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=UUID_PK),
        sa.Column("kind", sa.String(30), nullable=False, unique=True),
        sa.Column("allowed", sa.Boolean, nullable=False),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_admins.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=TS, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("platform_connection_access")
