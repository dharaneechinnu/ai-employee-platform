"""Sarvam AI as a supported provider

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-21 10:00:00.000000

Sarvam speaks the OpenAI chat format at https://api.sarvam.ai/v1, so it
needs only a row here and a line in the adapter's base-URL table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO supported_providers
                (id, key, display_name, kind, enabled, trains_on_data, default_model,
                 docs_url, created_at, updated_at)
            VALUES
                (gen_random_uuid(), 'sarvam', 'Sarvam AI', 'llm', true, false, 'sarvam-30b',
                 'https://docs.sarvam.ai', now(), now())
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM supported_providers WHERE key = 'sarvam'"))
