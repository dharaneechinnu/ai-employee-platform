"""Request dependencies: who is calling, which company, and what they may do.

Two rules are enforced here and nowhere else:

1. The active company is resolved from the caller's **memberships**,
   never taken on trust from the request body. A client cannot name a
   company it does not belong to.

2. A caller who asks for another company's resource gets **404**, not
   403. A 403 would confirm the resource exists.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthError, NotFoundError, PermissionDeniedError
from app.core.permissions import Permission, role_has
from app.core.security import decode_access_token
from app.db.models.identity import Role, User
from app.db.repositories.identity_repo import MembershipRepository, UserRepository
from app.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(slots=True)
class CurrentUser:
    user: User

    @property
    def id(self) -> uuid.UUID:
        return self.user.id


@dataclass(slots=True)
class RequestContext:
    """Everything a route needs to act safely: the caller, the company
    they are acting in, and their role there."""

    user: User
    org_id: uuid.UUID
    role: Role

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    def can(self, permission: Permission) -> bool:
        return role_has(self.role, permission)


async def get_current_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError()

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise AuthError("Your session is not valid. Please sign in again.") from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthError() from exc

    user = await UserRepository(session).get(user_id)
    if user is None or not user.is_active:
        raise AuthError()

    return CurrentUser(user=user)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


async def get_context(
    session: SessionDep,
    current: CurrentUserDep,
    org_id: Annotated[uuid.UUID, Path(description="The company being acted in")],
) -> RequestContext:
    """Resolve the active company from the caller's own memberships.

    If they are not a member, this raises 404 rather than 403, so the
    response cannot be used to discover which company ids exist.
    """
    membership = await MembershipRepository(session).get_for_user_and_org(current.id, org_id)
    if membership is None:
        raise NotFoundError()

    return RequestContext(user=current.user, org_id=org_id, role=membership.role)


ContextDep = Annotated[RequestContext, Depends(get_context)]


def require_permission(permission: Permission):  # type: ignore[no-untyped-def]
    """Declare what a route needs. A test asserts every route uses this
    or is explicitly marked public, so a forgotten guard fails CI."""

    async def dependency(ctx: ContextDep) -> RequestContext:
        if not ctx.can(permission):
            raise PermissionDeniedError()
        return ctx

    return dependency


async def get_refresh_token_cookie(
    refresh_token: Annotated[str | None, Header(alias="Cookie")] = None,
) -> str | None:
    """Pull the refresh token out of the Cookie header.

    Read from a cookie rather than the body so the browser sends it
    automatically and JavaScript cannot read it.
    """
    if not refresh_token:
        return None
    for part in refresh_token.split(";"):
        name, _, value = part.strip().partition("=")
        if name == REFRESH_COOKIE_NAME:
            return value or None
    return None


REFRESH_COOKIE_NAME = "refresh_token"
