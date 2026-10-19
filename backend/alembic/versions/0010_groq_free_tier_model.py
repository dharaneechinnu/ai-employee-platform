"""Point Groq at a model a free key can actually reach.

Groq's seeded default was ``llama-3.3-70b-versatile``. Groq still
lists it, but it now sits behind a sales contact, so a free key is
told ``model_not_found`` — which reads like a broken key rather than
a model the account cannot reach. People then regenerate a credential
that was never the problem.

``openai/gpt-oss-20b`` is on the free tier and supports tool calling,
which this product cannot work without.

Migration 0008 already moved every template and employee onto "auto",
so this only has to correct the provider row that "auto" resolves
through, and the connection that failed its test because of it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_GROQ = "llama-3.3-70b-versatile"
NEW_GROQ = "openai/gpt-oss-20b"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE supported_providers
           SET default_model = '{NEW_GROQ}', updated_at = now()
         WHERE key = 'groq' AND default_model = '{OLD_GROQ}'
        """
    )

    # A key that failed only because the test asked for a model the
    # account cannot reach is not a bad key. Put it back to untested so
    # the UI invites another try instead of showing a failure the
    # customer cannot act on.
    op.execute(
        """
        UPDATE provider_configs
           SET status = 'untested', last_error = NULL
         WHERE provider_key = 'groq'
           AND status = 'failed'
           AND last_error LIKE '%model_not_found%'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE supported_providers
           SET default_model = '{OLD_GROQ}', updated_at = now()
         WHERE key = 'groq' AND default_model = '{NEW_GROQ}'
        """
    )
