"""Scope everything to a person instead of a company.

The product is for individuals now, so the tenant is a user. Every
table that carried `org_id` carries `owner_id` instead, pointing at
`users.id`, and `organizations`, `memberships` and `invitations` go.

What deliberately survives is the *shape*: one scope column on every
table holding someone's data, filtered in exactly one repository. That
is what makes "can one person read another's data?" a single-file
audit rather than a sweep of every query, and it is as useful for
25,000 individuals as it was for 25 companies. Only the noun changed.

Backfill picks the organisation's admin, falling back to its earliest
member, so a single-person workspace becomes that person's account and
nothing is orphaned. A company that somehow has no members at all
would leave rows with no owner, so those rows are deleted rather than
left unreachable and invisible to every query.

`downgrade` cannot restore which company anyone belonged to: the
memberships that said so are gone. It rebuilds the columns and gives
every user an organisation of their own, which is the same data under
the old shape, not the old data.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table that held customer data, scoped by company.
SCOPED = [
    "ai_employee_versions",
    "ai_employees",
    "approvals",
    "connections",
    "embedding_configs",
    "llm_calls",
    "mcp_servers",
    "memories",
    "memory_vectors_384",
    "memory_vectors_768",
    "memory_vectors_1024",
    "memory_vectors_1536",
    "notification_settings",
    "org_connection_access",
    "org_oauth_apps",
    "policies",
    "provider_configs",
    "reembed_jobs",
    "run_checkpoints",
    "run_events",
    "run_summaries",
    "runs",
    "tasks",
    "templates",
    "tool_invocations",
]

# `templates` holds both platform-wide rows (org_id NULL, seeded by
# migration 0003) and a company's own. The platform ones must stay
# visible to everybody, so their owner stays NULL.
NULLABLE_OWNER = {"templates"}


def upgrade() -> None:
    bind = op.get_bind()

    # One lookup for the whole migration: company -> the person who
    # becomes the owner of its rows.
    bind.execute(
        sa.text(
            """
            CREATE TEMPORARY TABLE _owner_of AS
            SELECT DISTINCT ON (m.org_id) m.org_id, m.user_id
              FROM memberships m
             ORDER BY m.org_id,
                      (m.role = 'admin') DESC,
                      m.created_at ASC
            """
        )
    )

    for table in SCOPED:
        nullable = table in NULLABLE_OWNER
        op.add_column(table, sa.Column("owner_id", sa.UUID(as_uuid=True), nullable=True))
        bind.execute(
            sa.text(
                f"""
                UPDATE {table} t
                   SET owner_id = o.user_id
                  FROM _owner_of o
                 WHERE o.org_id = t.org_id
                """  # noqa: S608 - names come from the constant above
            )
        )

        if not nullable:
            # A company with no members at all leaves rows nobody can
            # reach. Unreachable rows that still answer a COUNT are
            # worse than absent ones.
            bind.execute(sa.text(f"DELETE FROM {table} WHERE owner_id IS NULL"))  # noqa: S608
            op.alter_column(table, "owner_id", nullable=False)

        op.create_foreign_key(
            f"fk_{table}_owner", table, "users", ["owner_id"], ["id"], ondelete="CASCADE"
        )
        op.drop_column(table, "org_id")
        op.create_index(f"ix_{table}_owner", table, ["owner_id"])

    # The cap used to live on the company.
    op.add_column(
        "users",
        sa.Column("max_employees", sa.Integer(), nullable=False, server_default="5"),
    )
    bind.execute(
        sa.text(
            """
            UPDATE users u
               SET max_employees = o.max_employees
              FROM _owner_of w
              JOIN organizations o ON o.id = w.org_id
             WHERE w.user_id = u.id
            """
        )
    )

    # The invitation becomes a setup link for one person: the Platform
    # Admin creates the account, the owner sets their own password, so
    # staff never know a customer's credentials.
    op.create_table(
        "setup_tokens",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )

    # The company itself, and everything that only existed to describe
    # who belonged to one.
    op.drop_table("memberships")
    op.drop_table("invitations")
    op.drop_table("organizations")


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_table("setup_tokens")
    op.drop_column("users", "max_employees")

    op.create_table(
        "organizations",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("max_employees", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_table(
        "memberships",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "org_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(20), nullable=False, server_default="admin"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("org_id", "user_id", name="uq_membership"),
    )
    op.create_table(
        "invitations",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "org_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )

    # One organisation per person. The old memberships are gone, so
    # this is the same data in the old shape rather than the old data.
    bind.execute(
        sa.text(
            """
            INSERT INTO organizations (id, name, slug)
            SELECT u.id, COALESCE(u.full_name, u.email), 'user-' || replace(u.id::text, '-', '')
              FROM users u
            """
        )
    )
    bind.execute(
        sa.text("INSERT INTO memberships (org_id, user_id, role) SELECT id, id, 'admin' FROM users")
    )

    for table in SCOPED:
        op.add_column(table, sa.Column("org_id", sa.UUID(as_uuid=True), nullable=True))
        bind.execute(sa.text(f"UPDATE {table} SET org_id = owner_id"))  # noqa: S608
        if table not in NULLABLE_OWNER:
            bind.execute(sa.text(f"DELETE FROM {table} WHERE org_id IS NULL"))  # noqa: S608
            op.alter_column(table, "org_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_org", table, "organizations", ["org_id"], ["id"], ondelete="CASCADE"
        )
        op.drop_index(f"ix_{table}_owner", table_name=table)
        op.drop_column(table, "owner_id")
