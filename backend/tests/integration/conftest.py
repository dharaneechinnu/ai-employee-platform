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

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5433/ai_employee"
)

# DELETE rather than TRUNCATE CASCADE. TRUNCATE CASCADE empties every
# referencing table outright, which wipes the platform templates seeded
# by migration 0003 (they are rows in `templates` with org_id NULL).
# DELETE follows the ON DELETE CASCADE foreign keys instead, so
# company-scoped rows go and platform-wide rows stay.
ROOT_TABLES_TO_CLEAR = [
    "platform_admin_audit",  # FK to platform_admins is SET NULL, so clear it first
    "platform_admins",
    "organizations",  # cascades to memberships, employees, tasks, memory, org templates
    "users",  # cascades to memberships, refresh_tokens, tasks
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
class SeededCompany:
    org_id: uuid.UUID
    admin_email: str
    admin_token: str
    member_email: str
    member_token: str


async def _create_org(session: AsyncSession, name: str, slug: str) -> uuid.UUID:
    from app.db.models.organization import Organization

    org = Organization(name=name, slug=slug, max_employees=3)
    session.add(org)
    await session.flush()
    await session.commit()
    return org.id


async def seed_company(
    session: AsyncSession, api: AsyncClient, *, name: str, slug: str
) -> SeededCompany:
    """Create a company with one admin and one member, both signed in.

    Goes through the real invite-and-accept flow rather than inserting
    rows, so the fixture exercises the same path a user would.
    """
    from app.core.security import hash_password
    from app.db.models.identity import Membership, Role, User

    org_id = await _create_org(session, name, slug)

    admin_email = f"admin@{slug}.com"
    admin = User(email=admin_email, password_hash=hash_password("correct-horse-battery"))
    session.add(admin)
    await session.flush()
    session.add(Membership(user_id=admin.id, org_id=org_id, role=Role.ADMIN))
    await session.commit()

    login = await api.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": "correct-horse-battery"},
    )
    admin_token = login.json()["access_token"]

    invite = await api.post(
        f"/api/v1/orgs/{org_id}/invites",
        json={"email": f"member@{slug}.com", "role": "member"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    raw = invite.json()["invite_token"]

    accepted = await api.post(
        "/api/v1/auth/accept-invite",
        json={"token": raw, "password": "correct-horse-battery", "full_name": "A Member"},
    )

    return SeededCompany(
        org_id=org_id,
        admin_email=admin_email,
        admin_token=admin_token,
        member_email=f"member@{slug}.com",
        member_token=accepted.json()["access_token"],
    )
