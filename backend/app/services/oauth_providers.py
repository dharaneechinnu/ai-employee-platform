"""The OAuth apps behind one-click connections.

One OAuth app per provider is registered for the whole platform; each
person then signs in through it with their own account. What we keep is
that person's refresh token, encrypted with their key.

Scopes are the narrowest that still let the tools do their job, and
they follow the services the person chose when connecting (see
`app/agent/services.py`): someone who shares only a sheet is asked for
the Sheets permission and nothing else. With no choice made, the first
version's set is requested: Gmail's `gmail.modify` reads, drafts and
sends but cannot permanently delete; Drive is read-only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.services import DEFAULT_GRANT, scopes_for_grant
from app.config import Settings, get_settings
from app.core.crypto import decrypt
from app.db.models.policy import ConnectionKind


@dataclass(frozen=True, slots=True)
class OAuthProvider:
    kind: ConnectionKind
    display_name: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scopes: tuple[str, ...]
    # Extra parameters for the consent screen. Google only returns a
    # refresh token with offline access *and* a forced consent prompt.
    extra_params: tuple[tuple[str, str], ...] = ()

    def client_from_env(self, settings: Settings | None = None) -> tuple[str, str] | None:
        """(client_id, client_secret) from the environment, or None.

        The fallback, kept for local development and for an operator
        who would rather keep the secret out of the database. A row in
        `platform_oauth_apps` wins over this, so a Platform Admin can
        change it without a redeploy.
        """
        s = settings or get_settings()
        if self.kind is ConnectionKind.GOOGLE:
            pair = (s.google_client_id, s.google_client_secret)
        else:
            pair = (s.microsoft_client_id, s.microsoft_client_secret)
        if pair[0] and pair[1]:
            return pair[0], pair[1]
        return None

    def redirect_uri(self, settings: Settings | None = None) -> str:
        s = settings or get_settings()
        return f"{s.public_api_url.rstrip('/')}{s.api_v1_prefix}/oauth/{self.kind.value}/callback"

    def authorize(self, *, client_id: str, state: str) -> str:
        params = {
            "client_id": client_id,
            "redirect_uri": self.redirect_uri(),
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
            **dict(self.extra_params),
        }
        return f"{self.authorize_url}?{urlencode(params)}"


def _microsoft_base() -> str:
    return f"https://login.microsoftonline.com/{get_settings().microsoft_tenant}/oauth2/v2.0"


def get_oauth_provider(kind: str, grant: dict[str, str] | None = None) -> OAuthProvider | None:
    """`grant` is {service: level} for the permissions to ask for; None
    asks for the default set."""
    if kind == ConnectionKind.GOOGLE.value:
        return OAuthProvider(
            kind=ConnectionKind.GOOGLE,
            display_name="Google Workspace",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",  # noqa: S106 - a URL, not a secret
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
            scopes=(
                "openid",
                "email",
                "profile",
                *scopes_for_grant("google", grant or DEFAULT_GRANT["google"]),
            ),
            extra_params=(
                ("access_type", "offline"),
                ("prompt", "consent"),
                ("include_granted_scopes", "true"),
            ),
        )
    if kind == ConnectionKind.MICROSOFT.value:
        base = _microsoft_base()
        return OAuthProvider(
            kind=ConnectionKind.MICROSOFT,
            display_name="Microsoft 365",
            authorize_url=f"{base}/authorize",
            token_url=f"{base}/token",
            userinfo_url="https://graph.microsoft.com/v1.0/me",
            scopes=(
                "offline_access",
                "openid",
                "email",
                "profile",
                "User.Read",
                *scopes_for_grant("microsoft", grant or DEFAULT_GRANT["microsoft"]),
            ),
            extra_params=(("prompt", "select_account"),),
        )
    return None


async def resolve_client(
    session: AsyncSession,
    provider: OAuthProvider,
    owner_id: uuid.UUID | None = None,
) -> tuple[str, str] | None:
    """The credentials in force for this provider, or None if unset.

    Three sources, most specific first:

    1. the person's own app, if they registered one — its name on the
       consent screen, its quota, and nobody else in the way;
    2. the platform's app, registered once by the operator and shared
       by everyone who has not brought their own;
    3. the environment, for local development.

    A person's own app wins even when the platform has one, because
    registering it is a deliberate act. A disabled platform row beats
    the environment, or "turn it off" would quietly fail wherever the
    variables were still set.
    """
    from app.db.models.provider import (  # circular at import time
        PersonOAuthApp,
        PlatformOAuthApp,
    )

    if owner_id is not None:
        own = await session.scalar(
            select(PersonOAuthApp).where(
                PersonOAuthApp.owner_id == owner_id, PersonOAuthApp.provider == provider.kind
            )
        )
        if own is not None:
            return own.client_id, decrypt(own.client_secret_enc, scope=owner_id)

    app = await session.scalar(
        select(PlatformOAuthApp).where(PlatformOAuthApp.provider == provider.kind)
    )
    if app is not None:
        if not app.enabled:
            return None
        return app.client_id, decrypt(app.client_secret_enc)

    return provider.client_from_env()
