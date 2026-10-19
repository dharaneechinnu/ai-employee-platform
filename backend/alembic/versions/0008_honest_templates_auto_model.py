"""templates that match the real tools, and the automatic model

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-13 09:00:00.000000

Two fixes found by the UX audit.

1. Every AI Employee defaulted to the model "gemini-flash", which is not
   a real Gemini model id, so a first run would fail. Those become
   "auto": use whichever AI provider the company connected.

2. The built-in templates promised work no tool can do (pull requests,
   a CRM, uploaded handbooks) and came with no tools ticked. They now
   describe what the platform's tools really do, and tick them.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DB = ["list_tables", "describe_table", "run_query"]

TEMPLATES: dict[str, dict[str, object]] = {
    "DevOps Helper": {
        "description": "Looks into incidents with read-only database checks and writes up what happened.",
        "guided": {
            "what_it_does": "Investigate incidents and errors: check the database read-only, look up what the company already knows, and explain what happened and what to do next.",
            "what_it_must_never_do": "Never change data. Never email anyone without approval.",
            "tone": "Short and precise. Numbers first.",
            "when_to_ask_a_human": "Before sending anything outside the team.",
            "what_good_looks_like": "A short summary: what broke, when, how many were affected, and the next step.",
        },
        "tools": [*DB, "recall", "remember", "get_webpage", "delegate_to_specialist"],
        "max_steps": 15,
    },
    "Support Agent": {
        "description": "Reads customer email and writes draft replies for a person to send.",
        "guided": {
            "what_it_does": "Read incoming customer email in Gmail, work out what is being asked, and save a draft reply.",
            "what_it_must_never_do": "Never send an email. Never promise a refund or a deadline.",
            "tone": "Warm, plain and brief.",
            "when_to_ask_a_human": "Before anything involving money or a complaint.",
            "what_good_looks_like": "A draft that answers the question and needs no editing.",
        },
        "tools": ["gmail_search", "gmail_read", "gmail_create_draft", "recall"],
        "max_steps": 10,
    },
    "Data Analyst": {
        "description": "Asks your database questions, read-only, and writes up the answer.",
        "guided": {
            "what_it_does": "Turn a plain-English question into a read-only database query and summarise the result.",
            "what_it_must_never_do": "Never change or delete data. Read only.",
            "tone": "Factual. Numbers first.",
            "when_to_ask_a_human": "If the question is ambiguous, ask rather than guess.",
            "what_good_looks_like": "A short answer with the numbers and the query used.",
        },
        "tools": [*DB, "recall"],
        "max_steps": 12,
    },
    "Sales Assistant": {
        "description": "Prepares meeting notes from your email, calendar and the customer's website.",
        "guided": {
            "what_it_does": "Before a customer meeting, read recent emails and the calendar invite, check the customer's website, and write a short briefing note.",
            "what_it_must_never_do": "Never contact a customer directly.",
            "tone": "Professional and concise.",
            "when_to_ask_a_human": "Before creating or changing any calendar event.",
            "what_good_looks_like": "A one-page note: who they are, what they asked for, and open questions.",
        },
        "tools": [
            "gmail_search",
            "gmail_read",
            "google_calendar_list",
            "get_webpage",
            "recall",
            "remember",
        ],
        "max_steps": 12,
    },
    "HR Helper": {
        "description": "Answers staff questions from company memory and the handbook in Google Drive.",
        "guided": {
            "what_it_does": "Answer staff questions about company policy, using company memory and the handbook in Google Drive.",
            "what_it_must_never_do": "Never guess at policy. If nothing covers it, say so.",
            "tone": "Friendly and clear.",
            "when_to_ask_a_human": "Anything about pay, discipline or personal circumstances.",
            "what_good_looks_like": "A direct answer that quotes the relevant policy.",
        },
        "tools": ["recall", "google_drive_search", "google_drive_read"],
        "max_steps": 8,
    },
}


def upgrade() -> None:
    conn = op.get_bind()
    for name, t in TEMPLATES.items():
        conn.execute(
            sa.text(
                """
            UPDATE templates
               SET description = :description,
                   config = config
                       || jsonb_build_object('guided', CAST(:guided AS jsonb))
                       || jsonb_build_object('enabled_tools', CAST(:tools AS jsonb))
                       || jsonb_build_object('max_steps', CAST(:max_steps AS int)),
                   updated_at = now()
             WHERE org_id IS NULL AND name = :name
            """
            ),
            {
                "name": name,
                "description": t["description"],
                "guided": json.dumps(t["guided"]),
                "tools": json.dumps(t["tools"]),
                "max_steps": t["max_steps"],
            },
        )

    for table in ("templates", "ai_employee_versions"):
        op.execute(
            f"""
            UPDATE {table}
               SET config = jsonb_set(config, '{{model}}', '"auto"')
             WHERE config->>'model' = 'gemini-flash'
            """  # noqa: S608 - fixed table names, no user input
        )


def downgrade() -> None:
    # The template wording is not restored: the old text described tools
    # that do not exist. Only the model value goes back.
    for table in ("templates", "ai_employee_versions"):
        op.execute(
            f"""
            UPDATE {table}
               SET config = jsonb_set(config, '{{model}}', '"gemini-flash"')
             WHERE config->>'model' = 'auto'
            """  # noqa: S608 - fixed table names, no user input
        )
