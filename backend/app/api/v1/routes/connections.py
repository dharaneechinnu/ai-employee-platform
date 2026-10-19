"""Connection routes: link the outside apps AI Employees work in.

As with provider keys, there is no endpoint that returns a credential.
The list shows which account is connected and whether it works, never
the token or password behind it.

The OAuth callback is the one public route here. It is safe to leave
open because it trusts nothing in the request except the signed
`state`, which only this server can produce and which names the
company and person who started the sign-in.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.v1.deps import RequestContext, SessionDep, require_permission
from app.config import get_settings
from app.core.errors import AppError
from app.core.observability import get_logger
from app.core.permissions import Permission, role_has
from app.core.signed import InvalidSignedTokenError
from app.db.repositories.identity_repo import MembershipRepository
from app.services.connection_service import ConnectionService
from app.services.oauth_providers import get_oauth_provider

log = get_logger(__name__)

router = APIRouter(prefix="/orgs/{org_id}", tags=["connections"])
callback_router = APIRouter(tags=["connections"])

CanManage = Annotated[RequestContext, Depends(require_permission(Permission.CONNECTION_MANAGE))]
CanRead = Annotated[RequestContext, Depends(require_permission(Permission.EMPLOYEE_READ))]


class AvailableConnectionResponse(BaseModel):
    kind: str
    display_name: str
    description: str
    auth: str
    apps: list[str]
    configured: bool
    tools: list[str]
    fields: list[dict[str, str]]
    secret_label: str | None
    # Whether a Platform Admin has closed this one for us, kept apart
    # from `configured` so the page can say which it is: "nobody set
    # this up" and "your provider turned this off" lead somewhere
    # different.
    allowed: bool
    blocked_note: str | None


class ConnectionResponse(BaseModel):
    id: uuid.UUID
    kind: str
    display_name: str
    label: str
    account: str | None
    status: str
    credential_last4: str
    last_tested_at: datetime | None
    last_error: str | None
    enabled: bool
    created_at: datetime
    config: dict[str, Any]


class OAuthStartResponse(BaseModel):
    authorize_url: str


class ManualConnectionRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=100)
    secret: str = Field(min_length=1, max_length=1000)
    config: dict[str, Any] = Field(default_factory=dict)


class OwnOAuthAppRequest(BaseModel):
    client_id: str = Field(min_length=5, max_length=300)
    # Write-only, like every other credential here.
    client_secret: str = Field(min_length=5, max_length=500)


class OwnOAuthAppResponse(BaseModel):
    kind: str
    client_id: str
    secret_last4: str
    # Shown so it can be pasted into Google's or Microsoft's console.
    # A redirect that does not match to the character is the usual
    # reason a sign-in fails.
    redirect_uri: str


class ToggleRequest(BaseModel):
    enabled: bool


@router.get(
    "/connections/available",
    response_model=list[AvailableConnectionResponse],
    summary="Apps that can be connected",
)
async def available(ctx: CanRead, session: SessionDep) -> list[AvailableConnectionResponse]:
    return [
        AvailableConnectionResponse(**asdict(a))
        for a in await ConnectionService(session, ctx.org_id).available()
    ]


@router.get("/connections", response_model=list[ConnectionResponse], summary="Our connected apps")
async def list_connections(ctx: CanRead, session: SessionDep) -> list[ConnectionResponse]:
    # Members may see which apps are connected (it explains what their
    # AI Employees can do); only admins can change them.
    return [
        ConnectionResponse(**asdict(c))
        for c in await ConnectionService(session, ctx.org_id).list_all()
    ]


@router.post(
    "/connections/oauth/{kind}/start",
    response_model=OAuthStartResponse,
    summary="Begin a one-click connection",
)
async def oauth_start(kind: str, ctx: CanManage, session: SessionDep) -> OAuthStartResponse:
    url = await ConnectionService(session, ctx.org_id).start_oauth(kind, user_id=ctx.user_id)
    return OAuthStartResponse(authorize_url=url)


@router.post(
    "/connections",
    response_model=ConnectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect an app by hand (mailbox or database)",
)
async def create_manual(
    body: ManualConnectionRequest, ctx: CanManage, session: SessionDep
) -> ConnectionResponse:
    service = ConnectionService(session, ctx.org_id)
    conn = await service.create_manual(
        kind=body.kind, label=body.label, secret=body.secret, config=body.config
    )
    await session.refresh(conn)
    return ConnectionResponse(**asdict(service.view(conn)))


@router.post(
    "/connections/{connection_id}/test",
    response_model=ConnectionResponse,
    summary="Check a connection works",
)
async def test_connection(
    connection_id: uuid.UUID, ctx: CanManage, session: SessionDep
) -> ConnectionResponse:
    service = ConnectionService(session, ctx.org_id)
    conn = await service.test(connection_id)
    await session.refresh(conn)
    return ConnectionResponse(**asdict(service.view(conn)))


@router.patch(
    "/connections/{connection_id}",
    response_model=ConnectionResponse,
    summary="Pause or resume a connection",
)
async def toggle_connection(
    connection_id: uuid.UUID, body: ToggleRequest, ctx: CanManage, session: SessionDep
) -> ConnectionResponse:
    service = ConnectionService(session, ctx.org_id)
    conn = await service.set_enabled(connection_id, body.enabled)
    await session.refresh(conn)
    return ConnectionResponse(**asdict(service.view(conn)))


@router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect an app",
)
async def delete_connection(connection_id: uuid.UUID, ctx: CanManage, session: SessionDep) -> None:
    await ConnectionService(session, ctx.org_id).delete(connection_id)


def _back_to_app(**params: str) -> RedirectResponse:
    url = f"{get_settings().public_app_url.rstrip('/')}/connections?{urlencode(params)}"
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


@callback_router.get(
    "/oauth/{kind}/callback",
    summary="Where Google or Microsoft sends the admin back (public)",
    include_in_schema=False,
)
async def oauth_callback(
    kind: str,
    session: SessionDep,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    state: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    if error:
        # The admin pressed Cancel on the consent screen, most likely.
        return _back_to_app(error="The sign-in was cancelled.")
    if not code or not state:
        return _back_to_app(error="The sign-in did not complete.")

    try:
        org_id, user_id = ConnectionService.read_state(state, kind)
    except InvalidSignedTokenError as exc:
        return _back_to_app(error=str(exc))

    # Permissions are re-checked now, not trusted from when the sign-in
    # started: the person may have lost admin rights in between.
    membership = await MembershipRepository(session).get_for_user_and_org(user_id, org_id)
    if membership is None or not role_has(membership.role, Permission.CONNECTION_MANAGE):
        return _back_to_app(error="You no longer have permission to connect apps.")

    try:
        conn = await ConnectionService(session, org_id).complete_oauth(
            kind, code=code, user_id=user_id
        )
        await session.commit()
    except AppError as exc:
        return _back_to_app(error=exc.message)
    except Exception:
        log.exception("oauth_callback_failed", kind=kind)
        return _back_to_app(error="Something went wrong finishing the sign-in. Please try again.")

    return _back_to_app(connected=kind, account=conn.label)


@router.get(
    "/connections/oauth-apps",
    response_model=list[OwnOAuthAppResponse],
    summary="Our own sign-in apps",
)
async def list_own_oauth_apps(
    ctx: CanManage, session: SessionDep
) -> list[OwnOAuthAppResponse]:
    service = ConnectionService(session, ctx.org_id)
    saved = await service.own_oauth_apps()
    out: list[OwnOAuthAppResponse] = []
    for kind, row in saved.items():
        provider = get_oauth_provider(kind)
        if provider is None:
            continue
        out.append(
            OwnOAuthAppResponse(
                kind=kind,
                client_id=row["client_id"],
                secret_last4=row["secret_last4"],
                redirect_uri=provider.redirect_uri(),
            )
        )
    return out


@router.put(
    "/connections/oauth-apps/{kind}",
    response_model=OwnOAuthAppResponse,
    summary="Use our own sign-in app",
)
async def save_own_oauth_app(
    kind: str, body: OwnOAuthAppRequest, ctx: CanManage, session: SessionDep
) -> OwnOAuthAppResponse:
    """Switch one-click on for this company without anyone else acting.

    The platform operator can register one app for everybody; this is
    the other route, for a company that would rather its own name be
    on the consent screen, or that does not want to wait.
    """
    row = await ConnectionService(session, ctx.org_id).save_own_oauth_app(
        kind=kind, client_id=body.client_id, client_secret=body.client_secret
    )
    await session.commit()

    provider = get_oauth_provider(kind)
    assert provider is not None
    return OwnOAuthAppResponse(
        kind=kind,
        client_id=row.client_id,
        secret_last4=row.secret_last4,
        redirect_uri=provider.redirect_uri(),
    )


@router.delete(
    "/connections/oauth-apps/{kind}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop using our own app",
)
async def delete_own_oauth_app(kind: str, ctx: CanManage, session: SessionDep) -> None:
    await ConnectionService(session, ctx.org_id).delete_own_oauth_app(kind)
    await session.commit()
