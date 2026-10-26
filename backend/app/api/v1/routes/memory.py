"""Memory routes: browse, add, search, and switch embedding provider."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.agent.embeddings import AVAILABLE_MODELS
from app.api.v1.deps import ContextDep, SessionDep
from app.db.models.memory import MemoryKind
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/me", tags=["memory"])


class MemoryResponse(BaseModel):
    id: uuid.UUID
    content: str
    kind: MemoryKind
    embedding_model: str
    created_at: datetime


class CreateMemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    kind: MemoryKind = MemoryKind.FACT


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=50)


class SearchHitResponse(BaseModel):
    id: uuid.UUID
    content: str
    kind: MemoryKind
    score: float
    # "meaning", "keyword" or "both" — useful when tuning, and honest
    # about which half of hybrid search found it.
    matched_by: str


class EmbeddingProviderOption(BaseModel):
    key: str
    model: str
    dim: int
    needs_api_key: bool


class EmbeddingConfigResponse(BaseModel):
    provider_key: str
    model: str
    dim: int
    memories_needing_reembedding: int


class SetEmbeddingProviderRequest(BaseModel):
    provider_key: str
    api_key: str | None = None


def _to_response(memory: Any) -> MemoryResponse:
    return MemoryResponse(
        id=memory.id,
        content=memory.content,
        kind=memory.kind,
        embedding_model=memory.embedding_model,
        created_at=memory.created_at,
    )


@router.get("/memory", response_model=list[MemoryResponse], summary="Browse memories")
async def list_memory(ctx: ContextDep, session: SessionDep) -> list[MemoryResponse]:
    memories = await MemoryService(session, ctx.owner_id).list_memories()
    return [_to_response(m) for m in memories]


@router.post(
    "/memory",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a memory by hand",
)
async def create_memory(
    body: CreateMemoryRequest, ctx: ContextDep, session: SessionDep
) -> MemoryResponse:
    memory = await MemoryService(session, ctx.owner_id).remember(
        content=body.content,
        kind=body.kind,
        created_by=ctx.user_id,
    )
    return _to_response(memory)


@router.delete(
    "/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a memory"
)
async def delete_memory(memory_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> None:
    await MemoryService(session, ctx.owner_id).forget(memory_id)


@router.post("/memory/search", response_model=list[SearchHitResponse], summary="Search memory")
async def search_memory(
    body: SearchRequest, ctx: ContextDep, session: SessionDep
) -> list[SearchHitResponse]:
    hits = await MemoryService(session, ctx.owner_id).recall(body.query, limit=body.limit)
    return [
        SearchHitResponse(
            id=h.memory.id,
            content=h.memory.content,
            kind=h.memory.kind,
            score=round(h.score, 4),
            matched_by=h.matched_by,
        )
        for h in hits
    ]


@router.get(
    "/embedding-providers",
    response_model=list[EmbeddingProviderOption],
    summary="Embedding providers we can choose",
)
async def embedding_providers(ctx: ContextDep) -> list[EmbeddingProviderOption]:
    return [
        EmbeddingProviderOption(
            key=spec.provider_key,
            model=spec.model,
            dim=spec.dim,
            needs_api_key=spec.needs_api_key,
        )
        for spec in AVAILABLE_MODELS.values()
    ]


@router.get(
    "/embedding-config", response_model=EmbeddingConfigResponse, summary="Our current provider"
)
async def get_embedding_config(ctx: ContextDep, session: SessionDep) -> EmbeddingConfigResponse:
    service = MemoryService(session, ctx.owner_id)
    config = await service.config()
    return EmbeddingConfigResponse(
        provider_key=config.provider_key,
        model=config.model,
        dim=config.dim,
        memories_needing_reembedding=await service.needs_reembedding(),
    )


@router.put(
    "/embedding-config",
    response_model=EmbeddingConfigResponse,
    summary="Switch provider (requires re-embedding)",
)
async def set_embedding_config(
    body: SetEmbeddingProviderRequest, ctx: ContextDep, session: SessionDep
) -> EmbeddingConfigResponse:
    """Switching provider invalidates every existing vector.

    Vectors from two models cannot be compared — the arithmetic works
    and the answer is meaningless — so search refuses to run until
    everything has been re-embedded. The count in the response tells
    the UI how much work that is.
    """
    service = MemoryService(session, ctx.owner_id)
    config = await service.set_provider(provider_key=body.provider_key, api_key=body.api_key)
    return EmbeddingConfigResponse(
        provider_key=config.provider_key,
        model=config.model,
        dim=config.dim,
        memories_needing_reembedding=await service.needs_reembedding(),
    )


@router.post("/embedding-config/reembed", summary="Re-embed everything with the current provider")
async def reembed(ctx: ContextDep, session: SessionDep) -> dict[str, int]:
    processed = await MemoryService(session, ctx.owner_id).reembed_all()
    return {"reembedded": processed}
