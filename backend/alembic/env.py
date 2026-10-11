"""Alembic environment.

The database URL comes from application settings, not from alembic.ini,
so there is exactly one place it is configured.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.config import get_settings
from app.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", str(get_settings().database_url))
target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Render custom column types as the plain type they really are.

    Autogenerate would otherwise write
    `app.db.models.base.StrEnumType(length=20)` into the migration,
    which makes a migration depend on application code. Migrations must
    stay frozen: if that class is later renamed or moved, every old
    migration breaks and the history stops replaying.

    StrEnumType is a VARCHAR underneath, so that is what gets written.
    """
    from pgvector.sqlalchemy import Vector

    from app.db.models.base import StrEnumType

    if type_ == "type" and isinstance(obj, StrEnumType):
        return f"sa.String(length={obj.impl.length})"  # type: ignore[union-attr]
    if type_ == "type" and isinstance(obj, Vector):
        # Third-party, not app code, so the import is safe to add.
        autogen_context.imports.add("import pgvector.sqlalchemy")  # type: ignore[attr-defined]
        return f"pgvector.sqlalchemy.Vector(dim={obj.dim})"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        render_item=render_item,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
