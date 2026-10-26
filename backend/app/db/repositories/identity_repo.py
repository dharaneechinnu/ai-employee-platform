"""Repositories for identity tables."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db.models.identity import (
    PlatformAdmin,
    PlatformAdminAudit,
    RefreshToken,
    SetupToken,
    User,
)
from app.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    async def exists_by_email(self, email: str) -> bool:
        return await self.get_by_email(email) is not None


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


class SetupTokenRepository(BaseRepository[SetupToken]):
    model = SetupToken

    async def get_by_token_hash(self, token_hash: str) -> SetupToken | None:
        return await self.session.scalar(
            select(SetupToken).where(SetupToken.token_hash == token_hash)
        )
