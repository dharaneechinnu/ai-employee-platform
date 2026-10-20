"""BYOK provider routes.

Note what is missing: there is no endpoint that returns an API key.
Not a masked one, not to the company that set it, not to the Platform
Admin. `key_last4` exists so the UI can show which key is in place
without the value ever leaving the database.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.v1.deps import ContextDep, SessionDep
from app.db.models.provider import ConnectionStatus
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


class ModelChoice(BaseModel):
    provider_key: str
    display_name: str
    model: str
    status: str
    trains_on_data: bool


@router.get(
    "/providers/available", response_model=list[AvailableProvider], summary="The provider menu"
)
async def available(ctx: ContextDep, session: SessionDep) -> list[AvailableProvider]:
    return [
        AvailableProvider(
            key=p.key,
            display_name=p.display_name,
            default_model=p.default_model,
            docs_url=p.docs_url,
            trains_on_data=p.trains_on_data,
        )
        for p in await ProviderService(session, ctx.owner_id).available()
    ]


@router.get(
    "/providers",
    response_model=list[ConnectedProviderResponse],
    summary="Which providers we have connected",
)
async def connected(ctx: ContextDep, session: SessionDep) -> list[ConnectedProviderResponse]:
    return [
        ConnectedProviderResponse(**asdict(c))
        for c in await ProviderService(session, ctx.owner_id).connected()
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

    match = next(c for c in await service.connected() if c.provider_key == body.provider_key)
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

    match = next(c for c in await service.connected() if c.provider_key == provider_key)
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
    """Only models from providers this company has actually connected,
    so the dropdown cannot offer something that will fail at run time."""
    return [
        ModelChoice(**choice)
        for choice in await ProviderService(session, ctx.owner_id).model_choices()
    ]
