"""who started a run, and the index History needs

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-27 18:00:00.000000

Tasks and runs record who started them ("chat", "schedule" or "manual"),
runs also keep the agent, and two indexes keep the History list fast.
Existing rows are filled in: an agent's task takes the trigger the
scheduler logged for it (a schedule when there is no record), and every
other task was a chat message.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("trigger", sa.String(length=20), server_default="chat", nullable=False),
    )
    op.add_column(
        "runs",
        sa.Column("trigger", sa.String(length=20), server_default="chat", nullable=False),
    )
    op.add_column("runs", sa.Column("agent_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_runs_agent_id", "runs", "agents", ["agent_id"], ["id"], ondelete="SET NULL"
    )

    op.execute(
        """
        UPDATE tasks t SET trigger = COALESCE(
            (SELECT e.payload ->> 'trigger' FROM scheduler_events e
              WHERE e.task_id = t.id AND e.type = 'agent_started'
                AND e.payload ->> 'trigger' IN ('schedule', 'manual')
              ORDER BY e.id DESC LIMIT 1),
            'schedule')
        WHERE t.agent_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE runs r SET agent_id = t.agent_id, trigger = t.trigger
        FROM tasks t WHERE t.id = r.task_id
        """
    )

    op.create_index("ix_runs_owner_created", "runs", ["owner_id", "created_at"])
    op.create_index("ix_runs_owner_agent_created", "runs", ["owner_id", "agent_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_runs_owner_agent_created", table_name="runs")
    op.drop_index("ix_runs_owner_created", table_name="runs")
    op.drop_constraint("fk_runs_agent_id", "runs", type_="foreignkey")
    op.drop_column("runs", "agent_id")
    op.drop_column("runs", "trigger")
    op.drop_column("tasks", "trigger")
