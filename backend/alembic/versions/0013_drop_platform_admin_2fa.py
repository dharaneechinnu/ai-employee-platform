"""Drop the second factor from Platform Admin sign-in.

Removed at the owner's request: the authenticator step was friction
on every sign-in, including every local test.

Recorded plainly, because this is a weakening and a reader deserves
to know it was a decision rather than an oversight. A Platform Admin
can create and suspend every company on the platform, so from here a
single leaked or guessed password reaches all of them. What still
stands: a separate token type that a company admin's token cannot
satisfy, an append-only audit log, and the absence of any platform
endpoint that returns customer content.

The columns go rather than linger unused. A `totp_secret_enc` nobody
verifies is worse than none: it reads like a live control to the next
person, and it is one more encrypted secret to carry around for no
benefit. `downgrade` therefore cannot restore the old secrets — it
rebuilds the columns, and every admin would need to re-enrol.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("platform_admins", "totp_secret_enc")
    op.drop_column("platform_admins", "totp_confirmed")


def downgrade() -> None:
    # Nullable on the way back: the old secrets are gone, so there is
    # nothing honest to put here. Re-enrolment is the only route.
    op.add_column("platform_admins", sa.Column("totp_secret_enc", sa.LargeBinary(), nullable=True))
    op.add_column(
        "platform_admins",
        sa.Column("totp_confirmed", sa.Boolean(), nullable=False, server_default="false"),
    )
