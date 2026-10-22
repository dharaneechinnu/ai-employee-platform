"""LangGraph's checkpointer, on our own database.

A paused run's graph state has to outlive the worker that paused it, so
it is written to Postgres after every step and read back when a person
decides. LangGraph ships a Postgres saver, but it needs a second database
driver (psycopg) that cannot run on the default Windows event loop. This
one uses the SQLAlchemy and asyncpg connection the rest of the app
already has, and every row carries the owner's id like any other table.

Only the async half of the interface is implemented, because the graphs
here are only ever run with `ainvoke`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.checkpoint import GraphCheckpoint, GraphCheckpointWrite


class SqlCheckpointSaver(BaseCheckpointSaver[str]):
    def __init__(self, maker: async_sessionmaker[AsyncSession], owner_id: uuid.UUID) -> None:
        super().__init__()
        self._maker = maker
        self._owner_id = owner_id

    # --------------------------------------------------------------- reads

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = str(config["configurable"]["thread_id"])
        ns = config["configurable"].get("checkpoint_ns", "")
        wanted = get_checkpoint_id(config)

        query = select(GraphCheckpoint).where(
            GraphCheckpoint.thread_id == thread_id,
            GraphCheckpoint.checkpoint_ns == ns,
            GraphCheckpoint.owner_id == self._owner_id,
        )
        if wanted:
            query = query.where(GraphCheckpoint.checkpoint_id == wanted)
        else:
            query = query.order_by(GraphCheckpoint.checkpoint_id.desc()).limit(1)

        async with self._maker() as session:
            row = await session.scalar(query)
            if row is None:
                return None
            return await self._tuple(session, row)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        query = select(GraphCheckpoint).where(GraphCheckpoint.owner_id == self._owner_id)
        if config is not None:
            query = query.where(
                GraphCheckpoint.thread_id == str(config["configurable"]["thread_id"]),
                GraphCheckpoint.checkpoint_ns == config["configurable"].get("checkpoint_ns", ""),
            )
            if wanted := get_checkpoint_id(config):
                query = query.where(GraphCheckpoint.checkpoint_id == wanted)
        if before is not None and (cutoff := get_checkpoint_id(before)):
            query = query.where(GraphCheckpoint.checkpoint_id < cutoff)
        query = query.order_by(GraphCheckpoint.checkpoint_id.desc())
        if limit is not None:
            query = query.limit(limit)

        async with self._maker() as session:
            rows = list((await session.scalars(query)).all())
            for row in rows:
                item = await self._tuple(session, row)
                if filter and not all(item.metadata.get(k) == v for k, v in filter.items()):
                    continue
                yield item

    async def _tuple(self, session: AsyncSession, row: GraphCheckpoint) -> CheckpointTuple:
        writes = (
            await session.scalars(
                select(GraphCheckpointWrite)
                .where(
                    GraphCheckpointWrite.thread_id == row.thread_id,
                    GraphCheckpointWrite.checkpoint_ns == row.checkpoint_ns,
                    GraphCheckpointWrite.checkpoint_id == row.checkpoint_id,
                    GraphCheckpointWrite.owner_id == self._owner_id,
                )
                .order_by(GraphCheckpointWrite.task_id, GraphCheckpointWrite.idx)
            )
        ).all()
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.checkpoint_id,
                }
            },
            checkpoint=self.serde.loads_typed((row.kind, row.checkpoint)),
            metadata=self.serde.loads_typed((row.kind, row.meta)),
            parent_config=(
                {
                    "configurable": {
                        "thread_id": row.thread_id,
                        "checkpoint_ns": row.checkpoint_ns,
                        "checkpoint_id": row.parent_checkpoint_id,
                    }
                }
                if row.parent_checkpoint_id
                else None
            ),
            pending_writes=[
                (w.task_id, w.channel, self.serde.loads_typed((w.kind, w.value))) for w in writes
            ],
        )

    # -------------------------------------------------------------- writes

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = str(config["configurable"]["thread_id"])
        ns = config["configurable"].get("checkpoint_ns", "")
        kind, blob = self.serde.dumps_typed(checkpoint)
        _, meta_blob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        values = {
            "owner_id": self._owner_id,
            "parent_checkpoint_id": config["configurable"].get("checkpoint_id"),
            "kind": kind,
            "checkpoint": blob,
            "meta": meta_blob,
        }
        async with self._maker() as session:
            await session.execute(
                insert(GraphCheckpoint)
                .values(
                    thread_id=thread_id, checkpoint_ns=ns, checkpoint_id=checkpoint["id"], **values
                )
                .on_conflict_do_update(
                    index_elements=["thread_id", "checkpoint_ns", "checkpoint_id"],
                    # Never let one person's write replace another's row.
                    set_=values,
                    where=GraphCheckpoint.owner_id == self._owner_id,
                )
            )
            await session.commit()
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = str(config["configurable"]["thread_id"])
        ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        async with self._maker() as session:
            for position, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, position)
                kind, blob = self.serde.dumps_typed(value)
                statement = insert(GraphCheckpointWrite).values(
                    thread_id=thread_id,
                    checkpoint_ns=ns,
                    checkpoint_id=checkpoint_id,
                    task_id=task_id,
                    idx=idx,
                    owner_id=self._owner_id,
                    channel=channel,
                    kind=kind,
                    value=blob,
                )
                keys = ["thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"]
                if idx < 0:
                    # Special channels (interrupts, resume values) are overwritten.
                    statement = statement.on_conflict_do_update(
                        index_elements=keys,
                        set_={"channel": channel, "kind": kind, "value": blob},
                        where=GraphCheckpointWrite.owner_id == self._owner_id,
                    )
                else:
                    statement = statement.on_conflict_do_nothing(index_elements=keys)
                await session.execute(statement)
            await session.commit()

    async def adelete_thread(self, thread_id: str) -> None:
        async with self._maker() as session:
            for table in (GraphCheckpointWrite, GraphCheckpoint):
                await session.execute(
                    delete(table).where(
                        table.thread_id == str(thread_id), table.owner_id == self._owner_id
                    )
                )
            await session.commit()

    # ------------------------------------------------- the sync half is unused

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        raise NotImplementedError("SqlCheckpointSaver is async only; use ainvoke.")

    def put(self, *args: Any, **kwargs: Any) -> RunnableConfig:
        raise NotImplementedError("SqlCheckpointSaver is async only; use ainvoke.")

    def put_writes(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("SqlCheckpointSaver is async only; use ainvoke.")


async def drop_threads(session: AsyncSession, thread_ids: Sequence[str]) -> None:
    """Forget the saved state of runs that will never resume (a rejected or
    expired approval), inside the caller's own transaction."""
    if not thread_ids:
        return
    ids = [str(t) for t in thread_ids]
    await session.execute(
        delete(GraphCheckpointWrite).where(GraphCheckpointWrite.thread_id.in_(ids))
    )
    await session.execute(delete(GraphCheckpoint).where(GraphCheckpoint.thread_id.in_(ids)))
