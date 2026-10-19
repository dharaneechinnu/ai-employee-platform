"""Somewhere to put the Google and Microsoft OAuth apps.

The one-click buttons on a company's Connections page were dead and
nothing in the product could turn them on: the client id and secret
could only arrive as environment variables, which means a redeploy,
which means a Platform Admin could not do it at all.

They are platform-wide by nature — Google and Microsoft issue one app
registration per *application*, and each company then grants that app
access to their own mailbox — so this sits beside `supported_providers`
with no org_id, and only a Platform Admin may write it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_oauth_apps",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("provider", sa.String(30), nullable=False, unique=True),
        sa.Column("client_id", sa.String(300), nullable=False),
        # No read path, here or anywhere: the UI is shown the last four
        # characters and nothing else.
        sa.Column("client_secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column("secret_last4", sa.String(4), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "updated_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("platform_admins.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("platform_oauth_apps")
