"""posting to Slack or Teams asks first, like sending an email

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-30 09:00:00.000000

The Slack and Teams tools (pack "chat") arrived without a starting
value, so they fell back to the catch-all for actions that cannot be
undone: Blocked. That made them unusable until a person found the
switch, and it disagreed with email, where sending starts on "Ask me
first". A message posted to a channel is the same kind of act, so it
gets the same default. A person's own setting is untouched.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO policy_defaults (id, scope, scope_value, side_effect, setting, created_at, updated_at)
        VALUES (gen_random_uuid(), 'pack', 'chat', 'destructive', 'ask', now(), now())
        ON CONFLICT ON CONSTRAINT uq_policy_default DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM policy_defaults "
        "WHERE scope = 'pack' AND scope_value = 'chat' AND side_effect = 'destructive'"
    )
