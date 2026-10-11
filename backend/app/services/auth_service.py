"""Authentication: invite acceptance, login, and refresh-token rotation.

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

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import (
    ConflictError,
    InvalidCredentialsError,
    NotFoundError,
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
from app.db.models.identity import Invitation, Membership, RefreshToken, Role, User
from app.db.repositories.identity_repo import (
    InvitationRepository,
    MembershipRepository,
    RefreshTokenRepository,
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
        self.memberships = MembershipRepository(session)
        self.invitations = InvitationRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
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

    # ------------------------------------------------------------- invites

    async def create_invitation(
        self,
        *,
        org_id: uuid.UUID,
        email: str,
        role: Role,
        invited_by: uuid.UUID | None,
    ) -> tuple[Invitation, str]:
        email = email.lower()

        existing_user = await self.users.get_by_email(email)
        if existing_user is not None:
            membership = await self.memberships.get_for_user_and_org(existing_user.id, org_id)
            if membership is not None:
                raise ConflictError("That person is already a member of this company.")

        raw_token = secrets.token_urlsafe(32)
        invitation = Invitation(
            org_id=org_id,
            email=email,
            role=role,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(hours=self.settings.invite_expiry_hours),
            invited_by=invited_by,
        )
        self.session.add(invitation)
        await self.session.flush()

        # The raw token is returned exactly once. Only its hash is stored,
        # so it cannot be recovered later - a lost link means a new invite.
        return invitation, raw_token

    async def accept_invitation(
        self, *, token: str, password: str, full_name: str | None
    ) -> IssuedTokens:
        invitation = await self.invitations.get_by_token_hash(hash_token(token))
        now = datetime.now(UTC)

        # One message for every failure mode - expired, already used, or
        # never existed. Distinguishing them would let someone probe for
        # valid tokens.
        if invitation is None or not invitation.is_usable(now):
            raise ValidationError("This invitation link is not valid or has expired.")

        user = await self.users.get_by_email(invitation.email)
        if user is None:
            user = User(
                email=invitation.email,
                password_hash=hash_password(password),
                full_name=full_name,
            )
            self.session.add(user)
            await self.session.flush()
        elif await self.memberships.get_for_user_and_org(user.id, invitation.org_id):
            raise ConflictError("You are already a member of this company.")

        self.session.add(
            Membership(user_id=user.id, org_id=invitation.org_id, role=invitation.role)
        )
        invitation.used_at = now
        user.last_login_at = now

        log.info("invitation_accepted", user_id=str(user.id), org_id=str(invitation.org_id))
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

    # ------------------------------------------------------------- members

    async def change_member_role(
        self, *, org_id: uuid.UUID, target_user_id: uuid.UUID, new_role: Role
    ) -> Membership:
        membership = await self.memberships.get_for_user_and_org(target_user_id, org_id)
        if membership is None:
            raise NotFoundError("That person is not a member of this company.")

        if (
            membership.role == Role.ADMIN
            and new_role != Role.ADMIN
            and await self.memberships.count_admins(org_id) <= 1
        ):
            # Without this the last admin can demote themselves and lock
            # the company out of its own settings, with no self-service
            # way back in.
            raise ConflictError("A company must keep at least one admin.")

        membership.role = new_role
        return membership

    async def remove_member(self, *, org_id: uuid.UUID, target_user_id: uuid.UUID) -> None:
        membership = await self.memberships.get_for_user_and_org(target_user_id, org_id)
        if membership is None:
            raise NotFoundError("That person is not a member of this company.")

        if membership.role == Role.ADMIN and await self.memberships.count_admins(org_id) <= 1:
            raise ConflictError("A company must keep at least one admin.")

        await self.session.delete(membership)
