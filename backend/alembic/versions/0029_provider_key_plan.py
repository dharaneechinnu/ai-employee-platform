"""which plan each provider key is on

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-27 18:00:00.000000

`provider_configs.plan` is "free" or "paid" (NULL = not said). A call on a
free key is recorded at no cost, so the cost view can show free usage as
free. Keys on providers with a free tier are marked free here; the person
can change it on the key's panel. Calls already recorded are left as they
were.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("provider_configs", sa.Column("plan", sa.String(10), nullable=True))
    op.execute(
        sa.text(
            "UPDATE provider_configs SET plan = 'free' WHERE provider_key IN "
            "(SELECT key FROM supported_providers WHERE free_tier AND NOT is_local "
            "AND kind = 'llm')"
        )
    )


def downgrade() -> None:
    op.drop_column("provider_configs", "plan")
