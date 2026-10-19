"""any AI provider, a chosen model, and MCP tool servers

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-18 09:00:00.000000

1. Claude (Anthropic) and Mistral join the provider menu, plus
   "custom": a company's own OpenAI-compatible server, which is how any
   open-source model (Llama, Qwen, DeepSeek, Mistral) on vLLM, Ollama,
   LM Studio or LiteLLM gets connected.
2. A company can pick which model each provider uses, instead of only
   the provider's default; the custom provider also stores its address.
3. `mcp_servers`: tool servers speaking the Model Context Protocol.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PROVIDERS = [
    {
        "key": "anthropic",
        "display_name": "Anthropic (Claude)",
        "default_model": "claude-opus-5-5",
        "docs_url": "https://console.anthropic.com/settings/keys",
    },
    {
        "key": "mistral",
        "display_name": "Mistral",
        "default_model": "mistral-small-latest",
        "docs_url": "https://console.mistral.ai/api-keys",
    },
    {
        "key": "custom",
        "display_name": "Your own server (open-source models)",
        "default_model": None,
        "docs_url": None,
    },
]


def upgrade() -> None:
    op.add_column("provider_configs", sa.Column("model", sa.String(length=200), nullable=True))
    op.add_column("provider_configs", sa.Column("base_url", sa.String(length=500), nullable=True))
    op.add_column("provider_configs", sa.Column("label", sa.String(length=100), nullable=True))

    insert = sa.text(
        """
        INSERT INTO supported_providers
            (id, key, display_name, kind, enabled, trains_on_data, default_model, docs_url,
             created_at, updated_at)
        VALUES
            (gen_random_uuid(), :key, :display_name, 'llm', true, false, :default_model,
             :docs_url, now(), now())
        ON CONFLICT (key) DO NOTHING
        """
    )
    for row in NEW_PROVIDERS:
        op.execute(insert.bindparams(**row))

    op.create_table(
        "mcp_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=30), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("token_enc", sa.LargeBinary(), nullable=True),
        sa.Column("token_last4", sa.String(length=8), nullable=True),
        sa.Column(
            "tools",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="untested"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "slug", name="uq_mcp_server_org_slug"),
    )
    op.create_index("ix_mcp_servers_org", "mcp_servers", ["org_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_org", table_name="mcp_servers")
    op.drop_table("mcp_servers")
    # A company that connected one of the new providers loses that key:
    # the code it would run with no longer exists after a downgrade.
    op.execute(
        sa.text(
            "DELETE FROM provider_configs WHERE provider_key IN ('anthropic', 'mistral', 'custom')"
        )
    )
    op.execute(
        sa.text("DELETE FROM supported_providers WHERE key IN ('anthropic', 'mistral', 'custom')")
    )
    op.drop_column("provider_configs", "label")
    op.drop_column("provider_configs", "base_url")
    op.drop_column("provider_configs", "model")
