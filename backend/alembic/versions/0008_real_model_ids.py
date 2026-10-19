"""Replace model names that no vendor actually answers to.

Two separate mistakes, both of which only surface when someone
connects a real key.

1. The seeded templates carried ``"model": "gemini-flash"``. That is
   not a Gemini model id — the real ones are ``gemini-2.0-flash`` and
   ``gemini-2.5-flash``. The string was sent to Google verbatim and
   came back 400. Every AI Employee created from a template inherited
   it, so the fault was invisible until a key was connected.

2. Groq's default model was ``llama-3.3-70b-versatile``. Groq still
   lists it, but it now sits behind a sales contact, so a free key is
   told ``model_not_found`` — which reads like a broken key rather
   than a model the account cannot reach. ``openai/gpt-oss-20b`` is on
   the free tier and supports tool calling, which this product cannot
   work without.

The seed files for 0003 and 0004 are corrected too, so a database
built from scratch never carries these values. This migration is for
the databases that already exist.

Customer rows are rewritten only where they hold the exact broken
string. ``gemini-flash`` can never succeed, so leaving it would be
preserving a value that is guaranteed to fail rather than respecting
a choice someone made.
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

OLD_GEMINI = "gemini-flash"
NEW_GEMINI = "gemini:gemini-2.0-flash"

OLD_GROQ = "llama-3.3-70b-versatile"
NEW_GROQ = "openai/gpt-oss-20b"


def _retarget_model(table: str, old: str, new: str) -> None:
    op.execute(
        f"""
        UPDATE {table}
           SET config = jsonb_set(config, '{{model}}', '"{new}"'::jsonb)
         WHERE config->>'model' = '{old}'
        """
    )


def upgrade() -> None:
    # Only these two hold config. `ai_employees` carries identity and a
    # pointer to the current version; the configuration itself lives on
    # the version rows, which is what makes "why did it do that last
    # Tuesday?" answerable.
    for table in ("templates", "ai_employee_versions"):
        _retarget_model(table, OLD_GEMINI, NEW_GEMINI)

    op.execute(
        f"""
        UPDATE supported_providers
           SET default_model = '{NEW_GROQ}', updated_at = now()
         WHERE key = 'groq' AND default_model = '{OLD_GROQ}'
        """
    )

    # A key that failed its test only because the test asked for a
    # model the account cannot reach is not a bad key. Put it back to
    # untested so the UI invites another try instead of showing a
    # failure the customer cannot act on.
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
    for table in ("templates", "ai_employee_versions"):
        _retarget_model(table, NEW_GEMINI, OLD_GEMINI)

    op.execute(
        f"""
        UPDATE supported_providers
           SET default_model = '{OLD_GROQ}', updated_at = now()
         WHERE key = 'groq' AND default_model = '{NEW_GROQ}'
        """
    )
