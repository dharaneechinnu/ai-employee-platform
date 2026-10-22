"""saved state for LangGraph runs that wait for a person

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-22 12:00:00.000000

When a run needs an approval it is paused, and the graph's state is
written here so any worker can continue it after the decision. The old
`run_checkpoints` table stays until runs paused under it have drained.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.text("now()")


def _owner() -> sa.Column:
    return sa.Column(
        "owner_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "graph_checkpoints",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("checkpoint_ns", sa.String(200), primary_key=True, server_default=""),
        sa.Column("checkpoint_id", sa.String(64), primary_key=True),
        _owner(),
        sa.Column("parent_checkpoint_id", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("checkpoint", sa.LargeBinary, nullable=False),
        sa.Column("meta", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=TS, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=TS, nullable=False),
    )
    op.create_index("ix_graph_checkpoints_owner", "graph_checkpoints", ["owner_id"])

    op.create_table(
        "graph_checkpoint_writes",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("checkpoint_ns", sa.String(200), primary_key=True, server_default=""),
        sa.Column("checkpoint_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), primary_key=True),
        sa.Column("idx", sa.Integer, primary_key=True),
        _owner(),
        sa.Column("channel", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("value", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=TS, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=TS, nullable=False),
    )
    op.create_index("ix_graph_checkpoint_writes_owner", "graph_checkpoint_writes", ["owner_id"])


def downgrade() -> None:
    op.drop_table("graph_checkpoint_writes")
    op.drop_table("graph_checkpoints")
