"""policies approvals connections

Revision ID: 26d4b5a886d1
Revises: 0004
Create Date: 2026-10-11 15:49:46.541036
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_defaults",
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("scope_value", sa.String(length=100), nullable=False),
        sa.Column("side_effect", sa.String(length=20), nullable=True),
        sa.Column("setting", sa.String(length=20), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "scope_value", "side_effect", name="uq_policy_default"),
    )
    op.create_table(
        "connections",
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("credential_enc", sa.LargeBinary(), nullable=False),
        sa.Column("credential_last4", sa.String(length=8), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.UniqueConstraint("org_id", "kind", "label", name="uq_connection_org_kind_label"),
    )
    op.create_index("ix_connections_org", "connections", ["org_id"], unique=False)
    op.create_table(
        "policies",
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("scope_value", sa.String(length=100), nullable=False),
        sa.Column("side_effect", sa.String(length=20), nullable=True),
        sa.Column("setting", sa.String(length=20), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "scope", "scope_value", "side_effect", name="uq_policy_org"),
    )
    op.create_index("ix_policies_org", "policies", ["org_id"], unique=False)
    op.create_table(
        "approvals",
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("side_effect", sa.String(length=20), nullable=False),
        sa.Column("proposed", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approvals_expiry", "approvals", ["status", "expires_at"], unique=False)
    op.create_index("ix_approvals_org_status", "approvals", ["org_id", "status"], unique=False)
    op.create_table(
        "run_checkpoints",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pending_tool_call", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.execute(
        """
        INSERT INTO policy_defaults (id, scope, scope_value, side_effect, setting, created_at, updated_at)
        VALUES
        -- web: reading a public page is harmless
        (gen_random_uuid(), 'pack', 'web',      'read',        'auto',    now(), now()),
        -- database: read-only by design, so reading is automatic
        (gen_random_uuid(), 'pack', 'database', 'read',        'auto',    now(), now()),
        -- email: reading and drafting are safe, sending is not
        (gen_random_uuid(), 'pack', 'email',    'read',        'auto',    now(), now()),
        (gen_random_uuid(), 'pack', 'email',    'write',       'auto',    now(), now()),
        (gen_random_uuid(), 'pack', 'email',    'destructive', 'ask',     now(), now()),
        -- github arrives later; the defaults are set now so it is gated
        -- from its first day rather than retrofitted
        (gen_random_uuid(), 'pack', 'github',   'read',        'auto',    now(), now()),
        (gen_random_uuid(), 'pack', 'github',   'write',       'ask',     now(), now()),
        (gen_random_uuid(), 'pack', 'github',   'destructive', 'blocked', now(), now())
        """
    )


def downgrade() -> None:
    op.drop_table("run_checkpoints")
    op.drop_index("ix_approvals_org_status", table_name="approvals")
    op.drop_index("ix_approvals_expiry", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_policies_org", table_name="policies")
    op.drop_table("policies")
    op.drop_index("ix_connections_org", table_name="connections")
    op.drop_table("connections")
    op.drop_table("policy_defaults")
