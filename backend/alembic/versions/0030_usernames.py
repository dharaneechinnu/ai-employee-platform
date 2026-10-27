"""usernames for self-service sign-up

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-28 09:00:00.000000

`users.username` is what a person can sign in with besides their email.
Existing accounts get one from the part of their email before the @,
cleaned to the allowed characters (letters, digits, dot, hyphen,
underscore), cut to 30 and numbered when two would collide. Unique
ignoring case.
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base(email: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "", email.split("@", 1)[0]).lstrip("_.-")[:30]
    return cleaned.ljust(3, "0") if cleaned else "user"


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(30), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, email FROM users ORDER BY created_at, id")).all()
    used: set[str] = set()
    for user_id, email in rows:
        base = _base(email)
        candidate, n = base, 1
        while candidate.lower() in used:
            n += 1
            candidate = base[: 30 - len(str(n))] + str(n)
        used.add(candidate.lower())
        conn.execute(
            sa.text("UPDATE users SET username = :u WHERE id = :id"),
            {"u": candidate, "id": user_id},
        )

    op.alter_column("users", "username", nullable=False)
    op.create_index("uq_users_username_lower", "users", [sa.text("lower(username)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_username_lower", table_name="users")
    op.drop_column("users", "username")
