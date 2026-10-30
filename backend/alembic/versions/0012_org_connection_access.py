"""Let a Platform Admin open or close one connection for one company.

Registering an OAuth app decides whether a connection exists on the
platform at all. This decides whether a *particular* company may use
it — a customer on a plan that excludes email, or one who asked for
Drive to stay out of reach, without taking the app away from everyone.

Absence means inherit, so this table starts empty and changes nothing
for anyone already connected.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_connection_access",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column(
            "updated_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("platform_admins.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("org_id", "kind", name="uq_org_connection_access"),
    )


def downgrade() -> None:
    op.drop_table("org_connection_access")
