"""remove MCP tool servers

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-26 09:00:00.000000

The MCP ("tool servers") feature is gone. This drops `mcp_servers`
(created in 0009, moved from a company to a person in 0015), the
permission rules a person set for MCP tools ("mcp__<server>__<tool>"
names, or an "mcp__<server>" pack), and those tool names from saved
agents' tool lists.

The data is deleted, not archived: connected servers, their encrypted
tokens and cached tool lists, and those rules cannot be recovered.
`downgrade` recreates an empty `mcp_servers` table in the shape it had
just before this migration (person-owned, as 0015 left it), so the
schema round-trips; it does not bring any rows back.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS mcp_servers CASCADE"))
    op.execute(sa.text(r"DELETE FROM policies WHERE scope_value LIKE 'mcp\_\_%'"))
    op.execute(sa.text(r"DELETE FROM policy_defaults WHERE scope_value LIKE 'mcp\_\_%'"))
    # Saved agents keep their other tools, in the same order.
    op.execute(
        sa.text(
            r"""
            UPDATE agents a
               SET tools = (
                   SELECT COALESCE(jsonb_agg(t.name ORDER BY t.pos), '[]'::jsonb)
                     FROM jsonb_array_elements_text(a.tools) WITH ORDINALITY AS t(name, pos)
                    WHERE t.name NOT LIKE 'mcp\_\_%'
               )
             WHERE jsonb_typeof(a.tools) = 'array'
               AND EXISTS (
                   SELECT 1 FROM jsonb_array_elements_text(a.tools) AS n(name)
                    WHERE n.name LIKE 'mcp\_\_%'
               )
            """
        )
    )


def downgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_mcp_servers_owner", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mcp_servers_owner", "mcp_servers", ["owner_id"], unique=False)
