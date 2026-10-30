"""notification settings, and policy defaults for Google and Microsoft

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12 09:00:00.000000

Connections need no schema change: `connections.kind` is a VARCHAR, so
the new "google" and "microsoft" kinds are values, not a type change.

The new tool packs get platform defaults from their first day. Without
them the resolver's safe fallback would block every send outright,
which is safe but useless; "ask" is the point of the approval flow.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_settings",
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False),
        sa.Column("slack_enabled", sa.Boolean(), nullable=False),
        sa.Column("slack_webhook_enc", sa.LargeBinary(), nullable=True),
        sa.Column("slack_webhook_last4", sa.String(length=8), nullable=True),
        sa.Column("on_approval_requested", sa.Boolean(), nullable=False),
        sa.Column("on_task_completed", sa.Boolean(), nullable=False),
        sa.Column("on_task_failed", sa.Boolean(), nullable=False),
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
        sa.UniqueConstraint("org_id"),
    )

    op.execute(
        """
        INSERT INTO policy_defaults (id, scope, scope_value, side_effect, setting, created_at, updated_at)
        VALUES
        -- reading mail, calendars and files changes nothing
        (gen_random_uuid(), 'pack', 'google',    'read',        'auto', now(), now()),
        (gen_random_uuid(), 'pack', 'microsoft', 'read',        'auto', now(), now()),
        -- a calendar invite reaches other people, so a person checks it
        (gen_random_uuid(), 'pack', 'google',    'write',       'ask',  now(), now()),
        (gen_random_uuid(), 'pack', 'microsoft', 'write',       'ask',  now(), now()),
        -- sending email cannot be undone
        (gen_random_uuid(), 'pack', 'google',    'destructive', 'ask',  now(), now()),
        (gen_random_uuid(), 'pack', 'microsoft', 'destructive', 'ask',  now(), now()),
        -- a draft waits in the mailbox for a person, so it is safe to allow
        (gen_random_uuid(), 'tool', 'gmail_create_draft',   NULL, 'auto', now(), now()),
        (gen_random_uuid(), 'tool', 'outlook_create_draft', NULL, 'auto', now(), now())
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM policy_defaults WHERE scope_value IN "
        "('google', 'microsoft', 'gmail_create_draft', 'outlook_create_draft')"
    )
    op.drop_table("notification_settings")
