"""setup guide data on providers, and web search providers

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-27 12:00:00.000000

Adds what the setup screens need to the provider catalog (free tier,
runs locally, sign-up link, suggested order, guide steps) and two search
providers, Tavily and Brave, so a person can bring their own search key
the same way they bring an AI key.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _step(id_: str, title: str, detail: str, expect: str, url: str | None = None) -> dict[str, str]:
    step = {"id": id_, "title": title, "detail": detail, "expect": expect}
    if url:
        step["url"] = url
    return step


GEMINI_URL = "https://aistudio.google.com/apikey"
GROQ_URL = "https://console.groq.com/keys"
TAVILY_URL = "https://app.tavily.com/home"
BRAVE_URL = "https://api-dashboard.search.brave.com/app/keys"

GUIDES: dict[str, list[dict[str, str]]] = {
    "gemini": [
        _step(
            "signup",
            "Open Google AI Studio",
            "Sign in with a Google account and open the API keys page.",
            "You see a page titled API keys.",
            GEMINI_URL,
        ),
        _step(
            "create",
            "Create a key",
            "Choose Create API key and copy it.",
            "A long key starting with AIza is shown.",
        ),
        _step(
            "paste",
            "Paste it here",
            "Paste the key into the box and press Connect.",
            "The card shows the last four characters of your key.",
        ),
        _step(
            "test",
            "Test it",
            "We make one tiny request and pick a model that works.",
            "A green tick appears and a model name is filled in.",
        ),
    ],
    "groq": [
        _step(
            "signup",
            "Open the Groq console",
            "Create a free account or sign in, then open API Keys.",
            "You see a list of keys, empty at first.",
            GROQ_URL,
        ),
        _step(
            "create",
            "Create a key",
            "Choose Create API Key, name it, and copy it.",
            "A key starting with gsk_ is shown once.",
        ),
        _step(
            "paste",
            "Paste it here",
            "Paste the key into the box and press Connect.",
            "The card shows the last four characters of your key.",
        ),
        _step(
            "test",
            "Test it",
            "We make one tiny request and pick a model that works.",
            "A green tick appears and a model name is filled in.",
        ),
    ],
    "custom": [
        _step(
            "install",
            "Install a model runner",
            "Install a program that runs models on your computer, such as Ollama or LM Studio.",
            "The program opens and says it is running.",
        ),
        _step(
            "download",
            "Download a model",
            "Pick a small chat model in the program and let it download.",
            "The model appears in the program's list.",
        ),
        _step(
            "address",
            "Paste its address",
            "Use the program's local server address, for example http://localhost:11434/v1 "
            "for Ollama. A key is not needed.",
            "The address box is filled in.",
        ),
        _step(
            "test",
            "Test it",
            "We ask the server for its models and try one. This only works when this app can "
            "reach your machine.",
            "A green tick, or a clear message saying the address could not be reached.",
        ),
    ],
    "tavily": [
        _step(
            "signup",
            "Open Tavily",
            "Create an account or sign in.",
            "You see your dashboard with an API key box.",
            TAVILY_URL,
        ),
        _step(
            "create",
            "Copy your key",
            "Copy the key shown on the dashboard.",
            "A key starting with tvly- is shown.",
        ),
        _step(
            "paste",
            "Paste it here",
            "Paste the key and press Connect.",
            "The card shows the last four characters of your key.",
        ),
        _step(
            "test",
            "Test it",
            "We run one small search.",
            "A green tick appears.",
        ),
    ],
    "brave": [
        _step(
            "signup",
            "Open the Brave Search API",
            "Create an account, choose a plan, and open API Keys.",
            "You see the API keys page.",
            BRAVE_URL,
        ),
        _step(
            "create",
            "Create a key",
            "Add a key and copy it.",
            "A key is shown.",
        ),
        _step(
            "paste",
            "Paste it here",
            "Paste the key and press Connect.",
            "The card shows the last four characters of your key.",
        ),
        _step(
            "test",
            "Test it",
            "We run one small search.",
            "A green tick appears.",
        ),
    ],
}

# key -> (free_tier, is_local, signup_url, recommended_rank)
FLAGS: dict[str, tuple[bool, bool, str | None, int | None]] = {
    "gemini": (True, False, GEMINI_URL, 1),
    "groq": (True, False, GROQ_URL, 2),
    "custom": (False, True, None, 3),
    "openrouter": (True, False, "https://openrouter.ai/keys", None),
}


def upgrade() -> None:
    op.add_column(
        "supported_providers",
        sa.Column("free_tier", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "supported_providers",
        sa.Column("is_local", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("supported_providers", sa.Column("signup_url", sa.String(500), nullable=True))
    op.add_column("supported_providers", sa.Column("recommended_rank", sa.Integer(), nullable=True))
    op.add_column(
        "supported_providers",
        sa.Column(
            "guide",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    for key, (free, local, url, rank) in FLAGS.items():
        op.execute(
            sa.text(
                "UPDATE supported_providers SET free_tier = :free, is_local = :local, "
                "signup_url = :url, recommended_rank = :rank WHERE key = :key"
            ).bindparams(free=free, local=local, url=url, rank=rank, key=key)
        )

    for key, steps in GUIDES.items():
        op.execute(
            sa.text(
                "UPDATE supported_providers SET guide = CAST(:g AS jsonb) WHERE key = :key"
            ).bindparams(g=json.dumps(steps), key=key)
        )

    # The search providers. Not AIs: they carry no model and are never routed to.
    search = [
        ("tavily", "Tavily", TAVILY_URL, True, 1),
        ("brave", "Brave Search", BRAVE_URL, False, 2),
    ]
    for key, name, url, free, rank in search:
        op.execute(
            sa.text(
                "INSERT INTO supported_providers (id, key, display_name, kind, enabled, "
                "trains_on_data, docs_url, api_format, free_tier, is_local, signup_url, "
                "recommended_rank, guide, created_at, updated_at) VALUES "
                "(gen_random_uuid(), :key, :name, 'search', true, false, :url, 'openai', "
                ":free, false, :url, :rank, CAST(:g AS jsonb), now(), now())"
            ).bindparams(
                key=key, name=name, url=url, free=free, rank=rank, g=json.dumps(GUIDES[key])
            )
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM provider_configs WHERE provider_key IN ('tavily', 'brave')"))
    op.execute(sa.text("DELETE FROM supported_providers WHERE key IN ('tavily', 'brave')"))
    for col in ("guide", "recommended_rank", "signup_url", "is_local", "free_tier"):
        op.drop_column("supported_providers", col)
