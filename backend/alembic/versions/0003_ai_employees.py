"""ai employees, versions and templates

Revision ID: 6cd995c3753e
Revises: 0002
Create Date: 2026-10-11 13:26:44.247173
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_employees",
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("job_title", sa.String(length=100), nullable=True),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("avatar", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_version_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_employees_org_status", "ai_employees", ["org_id", "status"], unique=False
    )
    op.create_table(
        "templates",
        sa.Column("org_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_templates_org_id", "templates", ["org_id"], unique=False)
    op.create_table(
        "ai_employee_versions",
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["employee_id"], ["ai_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id", "version_no", name="uq_employee_version_no"),
    )
    op.create_index(
        "ix_ai_employee_versions_employee", "ai_employee_versions", ["employee_id"], unique=False
    )

    op.execute(
        """
        INSERT INTO templates (id, org_id, name, description, department, config, created_at, updated_at)
        VALUES
        (gen_random_uuid(), NULL, 'DevOps Helper',
         'Reads bug reports, looks at the code, and opens a fix.', 'Engineering',
         '{"guided": {"what_it_does": "Read bug reports, find the relevant code, and open a pull request with a fix.", "what_it_must_never_do": "Never delete code. Never push directly to the main branch.", "tone": "Short and precise.", "when_to_ask_a_human": "Before opening any pull request.", "what_good_looks_like": "A pull request with a clear title and an explanation of the change."}, "model": "gemini:gemini-2.0-flash", "temperature": 0.2, "max_steps": 15, "enabled_tools": []}'::jsonb,
         now(), now()),
        (gen_random_uuid(), NULL, 'Support Agent',
         'Reads customer email and writes draft replies.', 'Support',
         '{"guided": {"what_it_does": "Read incoming customer email, work out what is being asked, and write a draft reply.", "what_it_must_never_do": "Never send an email. Never promise a refund or a deadline.", "tone": "Warm, plain and brief.", "when_to_ask_a_human": "Before anything involving money or a complaint.", "what_good_looks_like": "A draft that answers the question and needs no editing."}, "model": "gemini:gemini-2.0-flash", "temperature": 0.3, "max_steps": 10, "enabled_tools": []}'::jsonb,
         now(), now()),
        (gen_random_uuid(), NULL, 'Data Analyst',
         'Asks the database questions and writes up the answer.', 'Operations',
         '{"guided": {"what_it_does": "Turn a plain-English question into a database query and summarise the result.", "what_it_must_never_do": "Never change or delete data. Read only.", "tone": "Factual. Numbers first.", "when_to_ask_a_human": "If the question is ambiguous, ask rather than guess.", "what_good_looks_like": "A short answer with the numbers and the query used."}, "model": "gemini:gemini-2.0-flash", "temperature": 0.1, "max_steps": 12, "enabled_tools": []}'::jsonb,
         now(), now()),
        (gen_random_uuid(), NULL, 'Sales Assistant',
         'Keeps customer records current and prepares notes.', 'Sales',
         '{"guided": {"what_it_does": "Research leads, keep CRM records current, and prepare notes before a meeting.", "what_it_must_never_do": "Never contact a customer directly. Never delete a record.", "tone": "Professional and concise.", "when_to_ask_a_human": "Before changing anything on a closed deal.", "what_good_looks_like": "An accurate record and a short briefing note."}, "model": "gemini:gemini-2.0-flash", "temperature": 0.3, "max_steps": 12, "enabled_tools": []}'::jsonb,
         now(), now()),
        (gen_random_uuid(), NULL, 'HR Helper',
         'Answers staff questions from company documents.', 'HR',
         '{"guided": {"what_it_does": "Answer staff questions about company policy, using the uploaded handbook.", "what_it_must_never_do": "Never guess at policy. If the handbook does not cover it, say so.", "tone": "Friendly and clear.", "when_to_ask_a_human": "Anything about pay, discipline or personal circumstances.", "what_good_looks_like": "A direct answer that quotes the relevant policy."}, "model": "gemini:gemini-2.0-flash", "temperature": 0.2, "max_steps": 8, "enabled_tools": []}'::jsonb,
         now(), now())
        """
    )


def downgrade() -> None:
    op.drop_index("ix_ai_employee_versions_employee", table_name="ai_employee_versions")
    op.drop_table("ai_employee_versions")
    op.drop_index("ix_templates_org_id", table_name="templates")
    op.drop_table("templates")
    op.drop_index("ix_ai_employees_org_status", table_name="ai_employees")
    op.drop_table("ai_employees")
