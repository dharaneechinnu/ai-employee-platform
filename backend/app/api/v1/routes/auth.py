"""Authentication routes.

Note there is no `/auth/register`. Accounts exist only by accepting an
invitation, and invitations are created by a Company Admin or by the
Platform Admin when a company is created. That removes a whole class of
abuse and is simpler than building a sign-up approval queue.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.v1.deps import REFRESH_COOKIE_NAME, CurrentUserDep, SessionDep
from app.config import get_settings
from app.core.errors import AuthError
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    SetupRequest,
    TokenResponse,
)
from app.services.auth_service import AuthService, IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=settings.refresh_token_days * 24 * 3600,
        # httponly: JavaScript cannot read it, so XSS cannot steal the session.
        httponly=True,
        # secure: never sent over plain HTTP. Relaxed in dev so localhost works.
        secure=settings.environment != "dev",
        # lax: sent on top-level navigation but not on cross-site POSTs,
        # which blocks the basic CSRF shape without breaking normal links.
        samesite="lax",
        path="/api/v1/auth",
    )


def _token_response(tokens: IssuedTokens, response: Response) -> TokenResponse:
    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post(
    "/setup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Set your password from a setup link",
)
async def complete_setup(
    body: SetupRequest,
    response: Response,
    session: SessionDep,
) -> TokenResponse:
    """The only place an account's password is ever set.

    The Platform Admin creates the account and sends the link; the
    password is chosen here, by its owner, so staff never know it and
    cannot sign in as anybody.
    """
    tokens = await AuthService(session).complete_setup(
        token=body.token, password=body.password, full_name=body.full_name
    )
    return _token_response(tokens, response)


@router.post("/login", response_model=TokenResponse, summary="Sign in")
async def login(body: LoginRequest, response: Response, session: SessionDep) -> TokenResponse:
    tokens = await AuthService(session).login(email=body.email, password=body.password)
    return _token_response(tokens, response)


@router.post("/refresh", response_model=TokenResponse, summary="Rotate the session")
async def refresh(request: Request, response: Response, session: SessionDep) -> TokenResponse:
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw:
        raise AuthError("No session to refresh.")

    tokens = await AuthService(session).refresh(raw_token=raw)
    return _token_response(tokens, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def logout(request: Request, response: Response, session: SessionDep) -> None:
    await AuthService(session).logout(raw_token=request.cookies.get(REFRESH_COOKIE_NAME))
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/v1/auth")


@router.get("/me", response_model=MeResponse, summary="Who am I")
async def me(current: CurrentUserDep) -> MeResponse:
    """No company to resolve any more: you are the scope.

    Everything this account can reach is filtered by this id in the
    repository layer, so there is nothing else for the client to pick.
    """
    return MeResponse(
        id=current.user.id,
        email=current.user.email,
        full_name=current.user.full_name,
        max_employees=current.user.max_employees,
    )


__all__ = ["router"]
