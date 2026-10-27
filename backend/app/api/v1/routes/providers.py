"""BYOK provider routes.

Note what is missing: there is no endpoint that returns an API key.
Not a masked one, not to the person who set it, not to the Platform
Admin. `key_last4` exists so the UI can show which key is in place
without the value ever leaving the database.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.v1.deps import ContextDep, SessionDep
from app.db.models.provider import ConnectionStatus, ProviderKind
from app.services.provider_service import ProviderService

router = APIRouter(prefix="/me", tags=["providers"])


class AvailableProvider(BaseModel):
    key: str
    display_name: str
    default_model: str | None
    docs_url: str | None
    # True means the provider may train on what is sent. For BYOK this
    # is a warning shown before connecting, not a block: it is their
    # key and their choice, but they must be told.
    trains_on_data: bool
    kind: ProviderKind = ProviderKind.LLM
    # For the setup cards and the guide, all kept as data on the catalog row.
    free_tier: bool = False
    is_local: bool = False
    signup_url: str | None = None
    # 1 = the easiest to start with. None = no suggestion.
    recommended_rank: int | None = None
    guide: list[dict[str, str]] = []


class ConnectRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=50)
    # Optional only for "custom": a self-hosted server often has no key.
    api_key: str = Field(default="", max_length=500)
    model: str | None = Field(default=None, max_length=200)
    # "custom" only: the OpenAI-compatible server's address and a name.
    base_url: str | None = Field(default=None, max_length=500)
    label: str | None = Field(default=None, max_length=100)


class SetModelRequest(BaseModel):
    # None goes back to the provider's default.
    model: str | None = Field(default=None, max_length=200)


class ConnectedProviderResponse(BaseModel):
    provider_key: str
    display_name: str
    key_last4: str
    status: ConnectionStatus
    last_tested_at: datetime | None
    last_error: str | None
    trains_on_data: bool
    default_model: str | None
    model_chosen: bool = False
    base_url: str | None = None
    strengths: list[str] | None = None
    plan: str | None = None


class SetPlanRequest(BaseModel):
    plan: Literal["free", "paid"]


class ModelChoice(BaseModel):
    provider_key: str
    display_name: str
    model: str
    status: str
    trains_on_data: bool


@router.get(
    "/providers/available", response_model=list[AvailableProvider], summary="The provider menu"
)
async def available(
    ctx: ContextDep, session: SessionDep, kind: ProviderKind = ProviderKind.LLM
) -> list[AvailableProvider]:
    return [
        AvailableProvider(
            key=p.key,
            display_name=p.display_name,
            default_model=p.default_model,
            docs_url=p.docs_url,
            trains_on_data=p.trains_on_data,
            kind=p.kind,
            free_tier=p.free_tier,
            is_local=p.is_local,
            signup_url=p.signup_url,
            recommended_rank=p.recommended_rank,
            guide=p.guide,
        )
        for p in await ProviderService(session, ctx.owner_id).available(kind)
    ]


@router.get(
    "/providers",
    response_model=list[ConnectedProviderResponse],
    summary="Which providers we have connected",
)
async def connected(
    ctx: ContextDep, session: SessionDep, kind: ProviderKind = ProviderKind.LLM
) -> list[ConnectedProviderResponse]:
    return [
        ConnectedProviderResponse(**asdict(c))
        for c in await ProviderService(session, ctx.owner_id).connected(kind)
    ]


@router.post(
    "/providers",
    response_model=ConnectedProviderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect a provider with our own key",
)
async def connect(
    body: ConnectRequest, ctx: ContextDep, session: SessionDep
) -> ConnectedProviderResponse:
    service = ProviderService(session, ctx.owner_id)
    await service.connect(
        provider_key=body.provider_key,
        api_key=body.api_key,
        model=body.model,
        base_url=body.base_url,
        label=body.label,
    )

    match = next(c for c in await service.connected(None) if c.provider_key == body.provider_key)
    return ConnectedProviderResponse(**asdict(match))


@router.post(
    "/providers/{provider_key}/test",
    response_model=ConnectedProviderResponse,
    summary="Check the key works",
)
async def test(
    provider_key: str,
    ctx: ContextDep,
    session: SessionDep,
) -> ConnectedProviderResponse:
    service = ProviderService(session, ctx.owner_id)
    await service.test(provider_key)
    await session.flush()

    match = next(c for c in await service.connected(None) if c.provider_key == provider_key)
    return ConnectedProviderResponse(**asdict(match))


@router.put(
    "/providers/{provider_key}/model",
    response_model=ConnectedProviderResponse,
    summary="Pick which model this provider runs",
)
async def set_model(
    provider_key: str, body: SetModelRequest, ctx: ContextDep, session: SessionDep
) -> ConnectedProviderResponse:
    service = ProviderService(session, ctx.owner_id)
    await service.set_model(provider_key, body.model)
    await session.flush()
    match = next(c for c in await service.connected() if c.provider_key == provider_key)
    return ConnectedProviderResponse(**asdict(match))


@router.put(
    "/providers/{provider_key}/plan",
    response_model=ConnectedProviderResponse,
    summary="Say whether this key is on a free or a paid plan",
)
async def set_plan(
    provider_key: str, body: SetPlanRequest, ctx: ContextDep, session: SessionDep
) -> ConnectedProviderResponse:
    service = ProviderService(session, ctx.owner_id)
    await service.set_plan(provider_key, body.plan)
    await session.flush()
    match = next(c for c in await service.connected(None) if c.provider_key == provider_key)
    return ConnectedProviderResponse(**asdict(match))


class ModelTryResponse(BaseModel):
    model: str
    ok: bool
    reason: str | None


class AutoModelResponse(BaseModel):
    provider: ConnectedProviderResponse
    # The model it settled on, or None when none of those tried worked.
    selected: str | None
    tried: list[ModelTryResponse]


@router.post(
    "/providers/{provider_key}/auto-model",
    response_model=AutoModelResponse,
    summary="Find a model this key can use and switch to it",
)
async def auto_model(provider_key: str, ctx: ContextDep, session: SessionDep) -> AutoModelResponse:
    service = ProviderService(session, ctx.owner_id)
    _config, tried = await service.auto_select(provider_key)
    await session.flush()
    match = next(c for c in await service.connected() if c.provider_key == provider_key)
    return AutoModelResponse(
        provider=ConnectedProviderResponse(**asdict(match)),
        selected=next((t.model for t in tried if t.ok), None),
        tried=[ModelTryResponse(model=t.model, ok=t.ok, reason=t.reason) for t in tried],
    )


@router.get(
    "/providers/{provider_key}/models",
    response_model=list[str],
    summary="Models this key can use, as the provider lists them",
)
async def list_models(provider_key: str, ctx: ContextDep, session: SessionDep) -> list[str]:
    return await ProviderService(session, ctx.owner_id).list_models(provider_key)


@router.delete(
    "/providers/{provider_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect a provider",
)
async def disconnect(provider_key: str, ctx: ContextDep, session: SessionDep) -> None:
    await ProviderService(session, ctx.owner_id).disconnect(provider_key)


@router.get("/models", response_model=list[ModelChoice], summary="Models we can pick")
async def models(ctx: ContextDep, session: SessionDep) -> list[ModelChoice]:
    """Only models from providers this person has actually connected,
    so the dropdown cannot offer something that will fail at run time."""
    return [
        ModelChoice(**choice)
        for choice in await ProviderService(session, ctx.owner_id).model_choices()
    ]
