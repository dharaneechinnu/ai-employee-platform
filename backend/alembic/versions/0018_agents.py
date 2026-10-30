"""agents: saved helpers a person designs by talking

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("handle", sa.String(40), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text, nullable=False),
        sa.Column("model", sa.String(200), nullable=False, server_default="auto"),
        sa.Column("routing", sa.String(20), nullable=False, server_default="balanced"),
        sa.Column("tools", postgresql.JSONB),
        sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.false()),
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
    )
    op.create_index("ix_agents_owner", "agents", ["owner_id"])
    op.create_index("uq_agents_owner_handle", "agents", ["owner_id", "handle"], unique=True)
    op.add_column(
        "conversations",
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("conversation_messages", sa.Column("draft", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_messages", "draft")
    op.drop_column("conversations", "agent_id")
    op.drop_table("agents")
