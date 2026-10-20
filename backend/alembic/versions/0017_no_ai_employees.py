"""Remove AI Employees.

Users create their own agents in chat now, so the named, configurable
AI Employees (and the templates, versions and per-person limit that
came with them) have nothing left to do.

This deletes data, and says so:

- Every task that was assigned to an AI Employee is deleted, along with
  its runs, steps, approvals and checkpoints (those cascade). Chat turns
  are kept: they never belonged to an employee.
- Memories that were private to one employee are deleted. They belong
  to a worker that no longer exists, and no screen could reach them.
- The AI Employee limit on each account goes, and so do the two
  notification settings that only ever applied to employee tasks.

What stays: every conversation, every shared memory, every connection,
provider key and permission.

`downgrade` is not offered. The rows are gone, so a downgrade could
restore the shape of the tables but not what was in them, and a
migration that claims to be reversible when it is not is worse than
one that says so.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # Tasks that were assigned to an employee. Runs, events, approvals
    # and checkpoints hang off them with ON DELETE CASCADE.
    bind.execute(sa.text("DELETE FROM tasks WHERE conversation_id IS NULL"))

    # IF EXISTS throughout. Dropping a column drops every index that
    # includes it, so by now the composite indexes that mentioned
    # employee_id may or may not still exist depending on the history
    # of the database, and this must not care which.
    bind.execute(sa.text("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_one_worker"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_tasks_employee"))
    op.drop_column("tasks", "employee_version_id")
    op.drop_column("tasks", "employee_id")
    op.alter_column("tasks", "conversation_id", nullable=False)

    # Memory had a scope only because there were several workers to
    # share or withhold it from. One person owns all of it now.
    bind.execute(sa.text("DELETE FROM memories WHERE scope = 'employee'"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_memories_org_employee"))
    op.drop_column("memories", "employee_id")
    op.drop_column("memories", "scope")
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_memories_owner ON memories (owner_id)"))
    op.drop_column("run_summaries", "employee_id")

    op.drop_table("ai_employee_versions")
    op.drop_table("ai_employees")
    op.drop_table("templates")

    op.drop_column("users", "max_employees")

    # "Tell me when a task finishes" only ever fired for employee tasks:
    # a chat reply shows up in the chat the person is already in.
    op.drop_column("notification_settings", "on_task_completed")
    op.drop_column("notification_settings", "on_task_failed")

    # The permission for handing work to another employee guarded a
    # tool that no longer exists.
    bind.execute(sa.text("DELETE FROM policy_defaults WHERE scope_value = 'delegation'"))
    bind.execute(
        sa.text(
            "DELETE FROM policies "
            "WHERE scope_value IN ('delegation', 'delegate_to_specialist')"
        )
    )


def downgrade() -> None:
    raise NotImplementedError(
        "0017 deleted employee tasks, employee-scoped memories and every AI "
        "Employee. The tables could be recreated but not what was in them, so "
        "this migration is not reversible. Restore from a backup taken before "
        "upgrading."
    )
