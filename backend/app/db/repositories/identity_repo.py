"""Repositories for identity tables."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db.models.identity import (
    Invitation,
    Membership,
    PlatformAdmin,
    PlatformAdminAudit,
    RefreshToken,
    Role,
    User,
)
from app.db.models.organization import Organization
from app.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    async def exists_by_email(self, email: str) -> bool:
        return await self.get_by_email(email) is not None


class MembershipRepository(BaseRepository[Membership]):
    model = Membership

    async def get_for_user_and_org(
        self, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> Membership | None:
        return await self.session.scalar(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.org_id == org_id,
            )
        )

    async def list_orgs_for_user(self, user_id: uuid.UUID) -> Sequence[tuple[Organization, Role]]:
        rows = await self.session.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Organization.name)
        )
        return [(org, role) for org, role in rows.all()]

    async def list_members(self, org_id: uuid.UUID) -> Sequence[tuple[User, Role]]:
        rows = await self.session.execute(
            select(User, Membership.role)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.org_id == org_id)
            .order_by(User.email)
        )
        return [(user, role) for user, role in rows.all()]

    async def count_admins(self, org_id: uuid.UUID) -> int:
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(Membership)
            .where(Membership.org_id == org_id, Membership.role == Role.ADMIN)
        )
        return (await self.session.scalar(stmt)) or 0


class InvitationRepository(BaseRepository[Invitation]):
    model = Invitation

    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        return await self.session.scalar(
            select(Invitation).where(Invitation.token_hash == token_hash)
        )

    async def list_pending(self, org_id: uuid.UUID) -> Sequence[Invitation]:
        result = await self.session.scalars(
            select(Invitation)
            .where(Invitation.org_id == org_id, Invitation.used_at.is_(None))
            .order_by(Invitation.created_at.desc())
        )
        return result.all()


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

    async def revoke_family(self, family_id: uuid.UUID) -> None:
        """Kill every token descended from one login.

        Called when an already-rotated token is presented again: that
        means it was captured, so the whole session is burned rather
        than letting the attacker and the user race each other.
        """
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    async def revoke_one(self, token: RefreshToken) -> None:
        token.revoked_at = datetime.now(UTC)


class PlatformAdminRepository(BaseRepository[PlatformAdmin]):
    model = PlatformAdmin

    async def get_by_email(self, email: str) -> PlatformAdmin | None:
        return await self.session.scalar(
            select(PlatformAdmin).where(PlatformAdmin.email == email.lower())
        )

    def record_audit(
        self,
        *,
        admin_id: uuid.UUID | None,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: str | None = None,
    ) -> PlatformAdminAudit:
        entry = PlatformAdminAudit(
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            created_at=datetime.now(UTC),
        )
        self.session.add(entry)
        return entry


class OrganizationRepository(BaseRepository[Organization]):
    """Not org-scoped: the organization *is* the tenant."""

    model = Organization

    async def get_by_slug(self, slug: str) -> Organization | None:
        return await self.session.scalar(select(Organization).where(Organization.slug == slug))

    async def list_all(self) -> Sequence[Organization]:
        """Platform-admin only. No tenant filter by design."""
        result = await self.session.scalars(select(Organization).order_by(Organization.created_at))
        return result.all()
