"""Integration fixtures: a real database, truncated between tests.

Test email addresses use ordinary domains, not `.test`. EmailStr
rejects reserved and special-use TLDs (.test, .localhost, .invalid),
which is correct behaviour for real users - those addresses are not
routable - so the fixtures have to look like real addresses too.

Truncating rather than recreating the schema keeps each test fast while
still giving it a clean slate. Tests that share state are tests that
pass alone and fail in CI.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("ENVIRONMENT", "test")

# A SEPARATE database, on purpose. These tests delete every
# organization between cases, so running them against the development
# database destroys whatever you were working with. TEST_DATABASE_URL
# overrides it; DATABASE_URL deliberately does not.
#
# The default is derived from DATABASE_URL rather than hard-coded,
# because the host and the api container reach Postgres by different
# names: localhost:5433 from a shell, postgres:5432 from inside
# Compose. Hard-coding either one makes the tests fail with a
# connection error in the other place.


def _test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    app_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5433/ai_employee"
    )
    base, _, _ = app_url.rpartition("/")
    return f"{base}/ai_employee_test"


DATABASE_URL = _test_database_url()

# The app itself reads DATABASE_URL, so point that at the test database
# too. Without this the API under test would write to the dev database
# while the fixtures cleaned a different one.
os.environ["DATABASE_URL"] = DATABASE_URL

# DELETE rather than TRUNCATE CASCADE. TRUNCATE CASCADE empties every
# referencing table outright, which wipes the platform templates seeded
# by migration 0003 (they are rows in `templates` with owner_id NULL).
# DELETE follows the ON DELETE CASCADE foreign keys instead, so
# company-scoped rows go and platform-wide rows stay.
ROOT_TABLES_TO_CLEAR = [
    "platform_admin_audit",  # FK to platform_admins is SET NULL, so clear it first
    # Platform-wide and reached by no cascade: nothing owns it, so
    # without this line one test's registered OAuth app is still there
    # for the next, and "did this create or replace?" silently flips.
    "platform_oauth_apps",
    "platform_service_access",
    "platform_admins",
    # One line now, because everything a person owns hangs off
    # them: deleting the user cascades to their AI Employees,
    # tasks, memory, connections and setup tokens.
    "users",
]


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
async def _fresh_connections_per_test() -> AsyncGenerator[None, None]:
    """Dispose the app's global connection pools around every test.

    Both the database engine and the arq Redis pool are module-level
    singletons, which is right in production (one pool for the process
    lifetime) but wrong under pytest: each test runs on a new event
    loop, so connections pooled on the previous loop fail with
    "Event loop is closed".
    """
    from app.db.session import dispose_engine
    from app.workers.queue import close_pool

    await dispose_engine()
    await close_pool()
    yield
    await dispose_engine()
    await close_pool()


@pytest.fixture(autouse=True)
async def clean_database() -> AsyncGenerator[None, None]:
    eng = create_async_engine(DATABASE_URL)
    async with eng.begin() as conn:
        for table in ROOT_TABLES_TO_CLEAR:
            # Table names come from the constant above, never from
            # input, and an identifier cannot be a bound parameter.
            await conn.execute(text(f"DELETE FROM {table}"))  # noqa: S608
    await eng.dispose()
    yield


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    eng = create_async_engine(DATABASE_URL)
    maker = async_sessionmaker(bind=eng, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.commit()
    await eng.dispose()


@pytest.fixture
async def api() -> AsyncGenerator[AsyncClient, None]:
    from app.main import create_app

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@dataclass(slots=True)
class SeededPerson:
    """One account, signed in.

    `owner_id` is the user's own id: on a personal product the person
    and the scope are the same thing, which is the whole point of the
    re-scope. Kept as a separate field so every test still reads the
    way it did, and so the day anything is shared there is one name to
    change rather than hundreds.
    """

    owner_id: uuid.UUID
    email: str
    token: str

    # The old fixture handed back an admin and a member of one
    # company. There are no roles now, so a test that needs two
    # parties seeds two people.
    @property
    def admin_token(self) -> str:
        return self.token

    @property
    def admin_email(self) -> str:
        return self.email


async def seed_person(
    session: AsyncSession, api: AsyncClient, *, email: str | None = None, name: str = "Person"
) -> SeededPerson:
    """Create an account and sign it in, through the real login route."""
    from app.core.security import hash_password
    from app.db.models.identity import User

    email = email or f"{uuid.uuid4().hex[:10]}@example.com"
    user = User(
        email=email,
        username=f"u{uuid.uuid4().hex[:12]}",
        full_name=name,
        password_hash=hash_password("correct-horse-battery"),
    )
    session.add(user)
    await session.flush()
    await session.commit()

    login = await api.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    return SeededPerson(owner_id=user.id, email=email, token=login.json()["access_token"])


async def seed_company(
    session: AsyncSession, api: AsyncClient, *, name: str, slug: str
) -> SeededPerson:
    """Compatibility shim for tests written against companies.

    A company of one is now simply a person, so the old call site
    still means something sensible.
    """
    return await seed_person(session, api, email=f"admin@{slug}.com", name=name)
