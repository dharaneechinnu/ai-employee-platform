"""person naming for the per-person access tables; drop the unused reembed_jobs

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-28 18:00:00.000000

The three tables staff rulings and a person's own OAuth apps live in
were named after companies (`org_*`) when the product was multi-tenant.
They are per-person data, so they now say so: `person_connection_access`,
`person_service_access`, `person_oauth_apps`. Their keys, indexes and
foreign keys are renamed with them. Staff audit rows written about one
person used the target type "organization"; they become "user", the
same as every other row about a person.

`reembed_jobs` was created for a background re-embedding job that was
never built (switching embedding provider re-embeds in the request), so
nothing reads or writes it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (old table, new table, [(old constraint/index name, new name), ...])
RENAMES: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "org_connection_access",
        "person_connection_access",
        [
            ("org_connection_access_pkey", "person_connection_access_pkey"),
            ("org_connection_access_updated_by_fkey", "person_connection_access_updated_by_fkey"),
            ("fk_org_connection_access_owner", "fk_person_connection_access_owner"),
            ("ix_org_connection_access_owner", "ix_person_connection_access_owner"),
        ],
    ),
    (
        "org_service_access",
        "person_service_access",
        [
            ("org_service_access_pkey", "person_service_access_pkey"),
            ("uq_org_service_access", "uq_person_service_access"),
            ("org_service_access_owner_id_fkey", "person_service_access_owner_id_fkey"),
            ("org_service_access_updated_by_fkey", "person_service_access_updated_by_fkey"),
            ("ix_org_service_access_owner", "ix_person_service_access_owner"),
        ],
    ),
    (
        "org_oauth_apps",
        "person_oauth_apps",
        [
            ("org_oauth_apps_pkey", "person_oauth_apps_pkey"),
            ("fk_org_oauth_apps_owner", "fk_person_oauth_apps_owner"),
            ("ix_org_oauth_apps_owner", "ix_person_oauth_apps_owner"),
        ],
    ),
]


def _rename(old_table: str, new_table: str, names: list[tuple[str, str]], *, back: bool) -> None:
    src, dst = (new_table, old_table) if back else (old_table, new_table)
    op.rename_table(src, dst)
    for old, new in names:
        a, b = (new, old) if back else (old, new)
        # Indexes (including those behind keys) rename with ALTER INDEX;
        # a constraint that owns an index renames its index with it.
        kind = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT 1 FROM pg_constraint WHERE conname = :n AND conrelid = CAST(:t AS regclass)"
                ),
                {"n": a, "t": dst},
            )
            .first()
        )
        if kind:
            op.execute(f'ALTER TABLE "{dst}" RENAME CONSTRAINT "{a}" TO "{b}"')
        else:
            op.execute(f'ALTER INDEX IF EXISTS "{a}" RENAME TO "{b}"')


def upgrade() -> None:
    for old_table, new_table, names in RENAMES:
        _rename(old_table, new_table, names, back=False)
    op.execute(
        "UPDATE platform_admin_audit SET target_type = 'user' WHERE target_type = 'organization'"
    )
    op.drop_table("reembed_jobs")


def downgrade() -> None:
    op.create_table(
        "reembed_jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("from_model", sa.String(length=100), nullable=True),
        sa.Column("to_model", sa.String(length=100), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_reembed_jobs_owner", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="reembed_jobs_pkey"),
    )
    op.create_index("ix_reembed_jobs_owner", "reembed_jobs", ["owner_id"])
    # The "organization" target type cannot be told apart from "user"
    # rows again, so those audit rows stay as "user".
    for old_table, new_table, names in reversed(RENAMES):
        _rename(old_table, new_table, names, back=True)
