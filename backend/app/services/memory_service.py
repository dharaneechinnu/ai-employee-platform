"""Memory: storing it, searching it, and switching provider safely."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.embeddings import (
    AVAILABLE_MODELS,
    DEFAULT_PROVIDER,
    EmbeddingProvider,
    build_embedding_provider,
)
from app.core.crypto import decrypt, encrypt
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.observability import get_logger
from app.db.models.memory import (
    VECTOR_TABLES,
    EmbeddingConfig,
    Memory,
    MemoryKind,
    MemoryScope,
)

log = get_logger(__name__)

# Meaning search alone misses exact strings: an error code or a file
# name is what a DevOps employee searches for most, and a vector model
# is poor at those. Keyword search alone misses paraphrase. Both,
# merged, beats either.
VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3


@dataclass(slots=True)
class SearchHit:
    memory: Memory
    score: float
    matched_by: str  # "meaning", "keyword" or "both"


class MemoryService:
    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        self.session = session
        self.org_id = org_id

    # ------------------------------------------------------------- config

    async def config(self) -> EmbeddingConfig:
        config = await self.session.get(EmbeddingConfig, self.org_id)
        if config is None:
            # Local by default: free, no key, no rate limit, and no
            # company document leaves the server.
            spec = AVAILABLE_MODELS[DEFAULT_PROVIDER]
            config = EmbeddingConfig(
                org_id=self.org_id,
                provider_key=spec.provider_key,
                model=spec.model,
                dim=spec.dim,
            )
            self.session.add(config)
            await self.session.flush()
        return config

    async def provider(self) -> EmbeddingProvider:
        config = await self.config()
        api_key = decrypt(config.api_key_enc, scope=self.org_id) if config.api_key_enc else None
        return build_embedding_provider(config.provider_key, api_key=api_key, model=config.model)

    async def set_provider(self, *, provider_key: str, api_key: str | None) -> EmbeddingConfig:
        """Switch provider. The caller must then re-embed everything.

        Vectors from two different models cannot be compared: the
        numbers compute but the answer is meaningless, and search
        silently returns nonsense. So switching is a deliberate act
        with a background job behind it, not a toggle.
        """
        spec = AVAILABLE_MODELS.get(provider_key)
        if spec is None:
            raise ValidationError(f"'{provider_key}' is not a supported embedding provider.")
        if spec.needs_api_key and not api_key:
            raise ValidationError(f"{provider_key} embeddings need an API key.")

        config = await self.config()
        config.provider_key = spec.provider_key
        config.model = spec.model
        config.dim = spec.dim
        config.api_key_enc = encrypt(api_key, scope=self.org_id) if api_key else None
        await self.session.flush()
        return config

    # ------------------------------------------------------------- write

    async def remember(
        self,
        *,
        content: str,
        kind: MemoryKind = MemoryKind.FACT,
        scope: MemoryScope = MemoryScope.ORG,
        employee_id: uuid.UUID | None = None,
        meta: dict[str, Any] | None = None,
        created_by: uuid.UUID | None = None,
    ) -> Memory:
        if scope is MemoryScope.EMPLOYEE and employee_id is None:
            raise ValidationError("An employee-scoped memory needs an employee.")

        config = await self.config()
        provider = await self.provider()
        vector = await provider.embed_one(content)

        memory = Memory(
            org_id=self.org_id,
            employee_id=employee_id if scope is MemoryScope.EMPLOYEE else None,
            scope=scope,
            kind=kind,
            content=content,
            embedding_model=config.model,
            embedding_dim=config.dim,
            meta=meta or {},
            created_by=created_by,
        )
        self.session.add(memory)
        await self.session.flush()

        vector_table = VECTOR_TABLES[config.dim]
        self.session.add(vector_table(memory_id=memory.id, org_id=self.org_id, embedding=vector))
        await self.session.flush()
        return memory

    async def forget(self, memory_id: uuid.UUID) -> None:
        memory = await self.get(memory_id)
        # Deleting the row removes it from search immediately: the
        # vector row cascades, so there is no window where a deleted
        # memory is still recalled.
        await self.session.delete(memory)

    async def get(self, memory_id: uuid.UUID) -> Memory:
        memory = await self.session.scalar(
            select(Memory).where(Memory.id == memory_id, Memory.org_id == self.org_id)
        )
        if memory is None:
            raise NotFoundError("No such memory.")
        return memory

    async def list_memories(
        self, *, employee_id: uuid.UUID | None = None, limit: int = 100
    ) -> list[Memory]:
        stmt = select(Memory).where(Memory.org_id == self.org_id)
        if employee_id is not None:
            stmt = stmt.where(or_(Memory.employee_id == employee_id, Memory.employee_id.is_(None)))
        result = await self.session.scalars(stmt.order_by(Memory.created_at.desc()).limit(limit))
        return list(result.all())

    # ------------------------------------------------------------- search

    async def recall(
        self, query: str, *, employee_id: uuid.UUID | None = None, limit: int = 5
    ) -> list[SearchHit]:
        config = await self.config()

        mismatched = await self.session.scalar(
            select(func.count())
            .select_from(Memory)
            .where(Memory.org_id == self.org_id, Memory.embedding_model != config.model)
        )
        if mismatched:
            # Refuse rather than return confident nonsense. Comparing
            # vectors from two models is like comparing kilograms with
            # kilometres: it computes, and it means nothing.
            raise ConflictError(
                f"{mismatched} memories were embedded with a different model. "
                "Re-embedding is needed before search will be accurate."
            )

        provider = await self.provider()
        query_vector = await provider.embed_one(query)
        vector_table = VECTOR_TABLES[config.dim]

        scope_filter = (
            or_(Memory.employee_id == employee_id, Memory.employee_id.is_(None))
            if employee_id is not None
            else Memory.employee_id.is_(None)
        )

        rows = await self.session.execute(
            select(Memory, vector_table.embedding.cosine_distance(query_vector).label("distance"))  # type: ignore[attr-defined]
            .join(vector_table, vector_table.memory_id == Memory.id)  # type: ignore[attr-defined]
            .where(Memory.org_id == self.org_id, scope_filter)
            .order_by(text("distance"))
            .limit(limit * 2)
        )

        by_id: dict[uuid.UUID, SearchHit] = {}
        for memory, distance in rows.all():
            by_id[memory.id] = SearchHit(
                memory=memory,
                score=VECTOR_WEIGHT * (1.0 - float(distance)),
                matched_by="meaning",
            )

        # The keyword half. A vector model is weak on exact strings, and
        # error codes and file names are exactly what gets searched for.
        keyword_rows = await self.session.execute(
            select(
                Memory,
                func.ts_rank(Memory.content_tsv, func.plainto_tsquery("english", query)).label(
                    "rank"
                ),
            )
            .where(
                Memory.org_id == self.org_id,
                scope_filter,
                Memory.content_tsv.op("@@")(func.plainto_tsquery("english", query)),
            )
            .order_by(text("rank DESC"))
            .limit(limit * 2)
        )

        for memory, rank in keyword_rows.all():
            contribution = KEYWORD_WEIGHT * float(rank)
            if memory.id in by_id:
                by_id[memory.id].score += contribution
                by_id[memory.id].matched_by = "both"
            else:
                by_id[memory.id] = SearchHit(
                    memory=memory, score=contribution, matched_by="keyword"
                )

        return sorted(by_id.values(), key=lambda h: h.score, reverse=True)[:limit]

    # ------------------------------------------------------------- re-embed

    async def needs_reembedding(self) -> int:
        config = await self.config()
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(Memory)
                .where(Memory.org_id == self.org_id, Memory.embedding_model != config.model)
            )
        ) or 0

    async def reembed_all(self, *, batch_size: int = 50) -> int:
        """Re-process every memory with the current provider.

        Runs in the background in production; synchronous here because
        the logic is the same and the batching is what matters.
        """
        config = await self.config()
        provider = await self.provider()
        vector_table = VECTOR_TABLES[config.dim]
        processed = 0

        while True:
            stale = (
                await self.session.scalars(
                    select(Memory)
                    .where(Memory.org_id == self.org_id, Memory.embedding_model != config.model)
                    .limit(batch_size)
                )
            ).all()
            if not stale:
                break

            vectors = await provider.embed([m.content for m in stale])

            for memory, vector in zip(stale, vectors, strict=True):
                for table in VECTOR_TABLES.values():
                    existing = await self.session.get(table, memory.id)
                    if existing is not None:
                        await self.session.delete(existing)

                await self.session.flush()
                self.session.add(
                    vector_table(memory_id=memory.id, org_id=self.org_id, embedding=vector)
                )
                memory.embedding_model = config.model
                memory.embedding_dim = config.dim
                processed += 1

            await self.session.flush()

        log.info("reembed_complete", org_id=str(self.org_id), processed=processed)
        return processed
