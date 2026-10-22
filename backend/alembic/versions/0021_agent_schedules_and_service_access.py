"""agents run on a schedule; service-level permissions; the builder tab goes

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-21 15:00:00.000000

Agents are made in Chat now, so the separate builder conversations are
turned into ordinary chats. An agent gains a schedule and the place its
runs are written; a task can say which agent started it; and the
platform can allow or deny each part of an app (Gmail, Drive, Sheets,
Calendar) for reading and for editing, for everyone or for one company.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.text("now()")
UUID_PK = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.execute("UPDATE conversations SET mode = 'general' WHERE mode = 'builder'")

    op.add_column("agents", sa.Column("schedule", postgresql.JSONB, nullable=True))
    op.add_column(
        "agents",
        sa.Column("schedule_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column("agents", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("last_status", sa.String(30), nullable=True))
    op.add_column("agents", sa.Column("last_summary", sa.String(1000), nullable=True))
    op.add_column(
        "agents",
        sa.Column(
            "run_conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("agents", sa.Column("max_steps", sa.Integer, nullable=False, server_default="40"))
    op.add_column(
        "agents",
        sa.Column("scope", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_agents_due", "agents", ["schedule_enabled", "next_run_at"])

    op.add_column(
        "tasks",
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "platform_service_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=UUID_PK),
        sa.Column("service", sa.String(50), nullable=False),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("allowed", sa.Boolean, nullable=False),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_admins.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=TS, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=TS, nullable=False),
        sa.UniqueConstraint("service", "level", name="uq_platform_service_access"),
    )
    op.create_table(
        "org_service_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=UUID_PK),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("service", sa.String(50), nullable=False),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("allowed", sa.Boolean, nullable=False),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_admins.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=TS, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=TS, nullable=False),
        sa.UniqueConstraint("owner_id", "service", "level", name="uq_org_service_access"),
    )
    op.create_index("ix_org_service_access_owner", "org_service_access", ["owner_id"])


def downgrade() -> None:
    op.drop_table("org_service_access")
    op.drop_table("platform_service_access")
    op.drop_column("tasks", "agent_id")
    op.drop_index("ix_agents_due", table_name="agents")
    for column in (
        "scope",
        "max_steps",
        "run_conversation_id",
        "last_summary",
        "last_status",
        "last_run_at",
        "next_run_at",
        "schedule_enabled",
        "schedule",
    ):
        op.drop_column("agents", column)
