"""Authentication: account setup, login, and refresh-token rotation.

The interesting part is rotation. Every refresh issues a new token and
revokes the old one, and every token descended from one login shares a
`family_id`. Presenting an already-revoked token means it was captured,
because the legitimate client would have moved on to the newer one — so
the entire family is revoked and both parties are logged out.

Logging out the real user too is deliberate. Half of a stolen session is
still a stolen session; ending it and forcing a fresh login is the only
outcome that does not leave an attacker with access.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import (
    InvalidCredentialsError,
    TokenReuseError,
    ValidationError,
)
from app.core.observability import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from app.db.models.identity import RefreshToken, User
from app.db.repositories.identity_repo import (
    RefreshTokenRepository,
    SetupTokenRepository,
    UserRepository,
)

log = get_logger(__name__)


@dataclass(slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self.setup_tokens = SetupTokenRepository(session)
        self.settings = get_settings()

    # ------------------------------------------------------------- tokens

    async def _issue(self, user: User, *, family_id: uuid.UUID | None = None) -> IssuedTokens:
        access = create_access_token(subject=user.id)
        raw_refresh = generate_refresh_token()

        self.session.add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id or uuid.uuid4(),
                token_hash=hash_token(raw_refresh),
                expires_at=datetime.now(UTC) + timedelta(days=self.settings.refresh_token_days),
            )
        )
        return IssuedTokens(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in=self.settings.access_token_minutes * 60,
        )

    # -------------------------------------------------------- first sign-in

    async def complete_setup(
        self, *, token: str, password: str, full_name: str | None
    ) -> IssuedTokens:
        """Set the password on an account the Platform Admin created.

        The admin creates the account but never a usable password, so
        this is the only way one is ever set, and staff never know it.
        """
        setup = await self.setup_tokens.get_by_token_hash(hash_token(token))
        now = datetime.now(UTC)

        # One message for every failure — expired, already used, or
        # never existed. Telling them apart would let someone probe for
        # valid tokens.
        if setup is None or setup.used_at is not None or setup.expires_at <= now:
            raise ValidationError("This setup link is not valid or has expired.")

        user = await self.users.get(setup.user_id)
        if user is None:
            raise ValidationError("This setup link is not valid or has expired.")

        user.password_hash = hash_password(password)
        if full_name:
            user.full_name = full_name
        setup.used_at = now
        user.last_login_at = now

        log.info("setup_completed", user_id=str(user.id))
        return await self._issue(user)

    # ------------------------------------------------------------- login

    async def login(self, *, email: str, password: str) -> IssuedTokens:
        user = await self.users.get_by_email(email)

        if user is None:
            # Hash anyway so a missing account and a wrong password take
            # roughly the same time. Otherwise response timing reveals
            # which email addresses have accounts.
            hash_password(password)
            raise InvalidCredentialsError()

        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()

        if not user.is_active:
            raise InvalidCredentialsError()

        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        user.last_login_at = datetime.now(UTC)
        log.info("login_succeeded", user_id=str(user.id))
        return await self._issue(user)

    # ------------------------------------------------------------- refresh

    async def refresh(self, *, raw_token: str) -> IssuedTokens:
        stored = await self.refresh_tokens.get_by_hash(hash_token(raw_token))
        now = datetime.now(UTC)

        if stored is None:
            raise InvalidCredentialsError("Session is no longer valid. Please sign in again.")

        if stored.revoked_at is not None:
            # A revoked token came back. The legitimate client would have
            # moved on to its replacement, so this one was captured. Burn
            # the whole family rather than let the attacker keep rotating.
            await self.refresh_tokens.revoke_family(stored.family_id)
            log.warning(
                "refresh_token_reuse_detected",
                user_id=str(stored.user_id),
                family_id=str(stored.family_id),
            )
            raise TokenReuseError()

        if stored.expires_at <= now:
            raise InvalidCredentialsError("Session expired. Please sign in again.")

        user = await self.users.get(stored.user_id)
        if user is None or not user.is_active:
            raise InvalidCredentialsError()

        await self.refresh_tokens.revoke_one(stored)
        return await self._issue(user, family_id=stored.family_id)

    async def logout(self, *, raw_token: str | None) -> None:
        if not raw_token:
            return
        stored = await self.refresh_tokens.get_by_hash(hash_token(raw_token))
        if stored is not None:
            # Revoke the family, not just this token: logging out should
            # end the session everywhere it was rotated to.
            await self.refresh_tokens.revoke_family(stored.family_id)
