"""Point Groq at a model a free key can actually reach.

Groq's seeded default was ``llama-3.3-70b-versatile``. Groq still
lists it, but it now sits behind a sales contact, so a free key is
told ``model_not_found`` — which reads like a broken key rather than
a model the account cannot reach. People then regenerate a credential
that was never the problem.

``openai/gpt-oss-20b`` is on the free tier and supports tool calling,
which this product cannot work without.

This also cleans up after a withdrawn migration. An earlier revision
numbered 0008 moved employees from the unusable "gemini-flash" onto
"gemini:gemini-2.0-flash". It was replaced by the 0008 now in the
tree, which moves them to "auto" instead — the better answer, because
"auto" follows whichever provider the company actually connected. Any
database that applied the withdrawn one keeps its pinned Gemini model
and never sees the replacement, since both carried revision 0008. So
that value is converted here. Databases that never saw it match
nothing and are unaffected.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_GROQ = "llama-3.3-70b-versatile"
NEW_GROQ = "openai/gpt-oss-20b"

WITHDRAWN_PIN = "gemini:gemini-2.0-flash"


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text(
            "UPDATE supported_providers"
            "   SET default_model = :new, updated_at = now()"
            " WHERE key = 'groq' AND default_model = :old"
        ),
        {"new": NEW_GROQ, "old": OLD_GROQ},
    )

    for table in ("templates", "ai_employee_versions"):
        bind.execute(
            sa.text(
                f"UPDATE {table}"  # noqa: S608 — a fixed pair of names, never input
                "   SET config = jsonb_set(config, '{model}', '\"auto\"'::jsonb)"
                " WHERE config->>'model' = :pinned"
            ),
            {"pinned": WITHDRAWN_PIN},
        )

    # A key that failed only because the test asked for a model the
    # account cannot reach is not a bad key. Put it back to untested so
    # the UI invites another try instead of showing a failure the
    # customer cannot act on.
    bind.execute(
        sa.text(
            "UPDATE provider_configs"
            "   SET status = 'untested', last_error = NULL"
            " WHERE provider_key = 'groq'"
            "   AND status = 'failed'"
            "   AND last_error LIKE '%model_not_found%'"
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE supported_providers"
            "   SET default_model = :old, updated_at = now()"
            " WHERE key = 'groq' AND default_model = :new"
        ),
        {"new": NEW_GROQ, "old": OLD_GROQ},
    )
