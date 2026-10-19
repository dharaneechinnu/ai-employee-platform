"""Let a company register its own Google or Microsoft app.

Until now one-click sign-in depended on the platform operator
registering an app first, which put them in the critical path of every
customer's setup. A company can now supply its own client id and
secret and switch one-click on for itself.

Resolution order becomes company, then platform, then environment, so
neither path blocks the other and a company that does nothing still
gets the platform's app if one exists.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_oauth_apps",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "org_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("client_id", sa.String(300), nullable=False),
        sa.Column("client_secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column("secret_last4", sa.String(4), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("org_id", "provider", name="uq_org_oauth_app"),
    )


def downgrade() -> None:
    op.drop_table("org_oauth_apps")
