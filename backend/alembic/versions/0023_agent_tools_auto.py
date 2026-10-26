"""agents choose their own tools from their instructions

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-25 12:00:00.000000

`tools_auto` says the agent's tool list was worked out from its
instructions, so it is worked out again when they change. A list a
person chose by hand (or that came with a drafted agent) stays as it is.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("tools_auto", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("agents", "tools_auto")
