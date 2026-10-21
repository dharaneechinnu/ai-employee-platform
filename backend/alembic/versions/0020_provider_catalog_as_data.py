"""providers as data: how to talk to each one lives in its row

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-21 11:00:00.000000

Until now the endpoint, the wire format and any extra auth header were
written in code, so every new provider needed a release. They are
columns now: a new provider is a row a Platform Admin adds while the
platform is running.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "sarvam": "https://api.sarvam.ai/v1",
}


def upgrade() -> None:
    op.add_column(
        "supported_providers",
        sa.Column("api_format", sa.String(20), nullable=False, server_default="openai"),
    )
    op.add_column("supported_providers", sa.Column("base_url", sa.String(500), nullable=True))
    op.add_column("supported_providers", sa.Column("auth_header", sa.String(60), nullable=True))

    for key, url in BASE_URLS.items():
        op.execute(
            sa.text("UPDATE supported_providers SET base_url = :url WHERE key = :key").bindparams(
                url=url, key=key
            )
        )
    for key in ("gemini", "anthropic"):
        op.execute(
            sa.text("UPDATE supported_providers SET api_format = :key WHERE key = :key").bindparams(
                key=key
            )
        )
    # Sarvam's docs show two auth headers and disagree on which is required.
    op.execute(
        sa.text(
            "UPDATE supported_providers SET auth_header = 'api-subscription-key' "
            "WHERE key = 'sarvam'"
        )
    )


def downgrade() -> None:
    op.drop_column("supported_providers", "auth_header")
    op.drop_column("supported_providers", "base_url")
    op.drop_column("supported_providers", "api_format")
