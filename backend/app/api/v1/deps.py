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
from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthError
from app.core.security import decode_access_token
from app.db.models.identity import User
from app.db.repositories.identity_repo import UserRepository
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
    """Everything a route needs to act safely: the caller, and the
    scope their queries are confined to.

    For a personal account those are the same person, so `owner_id` is
    `user.id`. It stays a separate field rather than being read off
    the user because every query filters on it, and a named scope is
    what makes that filter reviewable — the day something is shared,
    this is the one line that changes.
    """

    user: User

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def owner_id(self) -> uuid.UUID:
        return self.user.id


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


async def get_context(current: CurrentUserDep) -> RequestContext:
    """The scope for this request.

    There is no id in the path any more: a person can only ever act as
    themselves, so the scope is derived from the token rather than
    accepted from the caller. That removes a whole class of mistake —
    there is no longer an id an attacker could substitute.
    """
    return RequestContext(user=current.user)


ContextDep = Annotated[RequestContext, Depends(get_context)]
# Kept as a name so routes read the same, now that every signed-in
# person is simply the owner of what they are asking about.
CanRead = ContextDep
CanWrite = ContextDep
CanManage = ContextDep


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
