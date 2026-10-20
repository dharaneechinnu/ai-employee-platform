"""conversations: a personal, ChatGPT-style assistant with agent tools

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-20 09:00:00.000000

A chat turn runs as an ordinary task, so `tasks` gains
`conversation_id` and its AI Employee columns become optional. A check
constraint keeps exactly one of the two set: every task still has
exactly one thing doing the work.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default="New chat"),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="general"),
        sa.Column("model", sa.String(length=200), nullable=False, server_default="auto"),
        sa.Column("routing", sa.String(length=20), nullable=False, server_default="balanced"),
        sa.Column("team", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_owner_updated", "conversations", ["owner_id", "updated_at"])

    op.add_column(
        "tasks", sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_tasks_conversation",
        "tasks",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_tasks_conversation", "tasks", ["conversation_id"])
    op.alter_column("tasks", "employee_id", nullable=True)
    op.alter_column("tasks", "employee_version_id", nullable=True)
    op.create_check_constraint(
        "ck_tasks_one_worker",
        "tasks",
        "(employee_id IS NOT NULL) <> (conversation_id IS NOT NULL)",
    )

    op.create_table(
        "conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("model_reason", sa.String(length=300), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "tools_used",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_messages_conversation",
        "conversation_messages",
        ["conversation_id", "created_at"],
    )
    op.create_index("ix_conversation_messages_owner", "conversation_messages", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_owner", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_conversation", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    # Chat turns have no AI Employee, so they cannot survive the
    # columns becoming required again.
    op.execute(sa.text("DELETE FROM tasks WHERE conversation_id IS NOT NULL"))
    op.drop_constraint("ck_tasks_one_worker", "tasks", type_="check")
    op.alter_column("tasks", "employee_version_id", nullable=False)
    op.alter_column("tasks", "employee_id", nullable=False)
    op.drop_index("ix_tasks_conversation", table_name="tasks")
    op.drop_constraint("fk_tasks_conversation", "tasks", type_="foreignkey")
    op.drop_column("tasks", "conversation_id")
    op.drop_index("ix_conversations_owner_updated", table_name="conversations")
    op.drop_table("conversations")
