"""The AI provider catalog: add, change or pause a provider while the platform runs.

A provider is a row (where it is, which wire format it speaks, which
extra auth header it wants), so supporting a new one is an API call,
not a release. Nothing secret lives here: keys belong to people and
stay encrypted under their own account.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.urls import check_service_url
from app.db.models.provider import ProviderKind, SupportedProvider
from app.db.repositories.identity_repo import PlatformAdminRepository

_PROVIDER_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
_HEADER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,59}$")
API_FORMATS = ("openai", "anthropic", "gemini")
# Taken: it has its own screen and meaning.
_RESERVED_KEYS = {"custom"}


class ProviderCatalog:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.admins = PlatformAdminRepository(session)

    async def all(self) -> list[SupportedProvider]:
        rows = await self.session.scalars(
            select(SupportedProvider)
            .where(SupportedProvider.kind == ProviderKind.LLM)
            .order_by(SupportedProvider.display_name)
        )
        return list(rows.all())

    async def save(
        self,
        *,
        admin_id: uuid.UUID,
        key: str,
        display_name: str,
        base_url: str,
        api_format: str = "openai",
        auth_header: str | None = None,
        default_model: str | None = None,
        docs_url: str | None = None,
        trains_on_data: bool = False,
    ) -> SupportedProvider:
        key = key.strip().lower()
        if not _PROVIDER_KEY.match(key) or key in _RESERVED_KEYS:
            raise ValidationError(
                "The key is a short lowercase name like 'sarvam' (letters, numbers, - and _)."
            )
        if api_format not in API_FORMATS:
            raise ValidationError(f"The format must be one of: {', '.join(API_FORMATS)}.")
        auth_header = (auth_header or "").strip() or None
        if auth_header and not _HEADER_NAME.match(auth_header):
            raise ValidationError("That is not a valid header name.")
        # Every call goes to this address with a person's key attached, so
        # it gets the same checks as an address a person types themselves.
        cleaned_url = check_service_url(base_url, what="provider")

        row = await self.session.scalar(
            select(SupportedProvider).where(SupportedProvider.key == key)
        )
        created = row is None
        if row is None:
            row = SupportedProvider(key=key, kind=ProviderKind.LLM)
            self.session.add(row)
        row.display_name = display_name.strip()[:100]
        row.base_url = cleaned_url
        row.api_format = api_format
        row.auth_header = auth_header
        row.default_model = (default_model or "").strip()[:100] or None
        row.docs_url = (docs_url or "").strip()[:500] or None
        row.trains_on_data = trains_on_data
        row.enabled = True
        await self.session.flush()

        self.admins.record_audit(
            admin_id=admin_id,
            action="provider_added" if created else "provider_updated",
            target_type="provider",
            target_id=key,
            detail=f"{api_format} at {cleaned_url}",
        )
        return row

    async def set_enabled(
        self, *, admin_id: uuid.UUID, key: str, enabled: bool
    ) -> SupportedProvider:
        """Pause rather than delete: people already connected keep a row
        to point at, and it can come back."""
        row = await self.session.scalar(
            select(SupportedProvider).where(SupportedProvider.key == key)
        )
        if row is None:
            raise NotFoundError(f"No such provider: '{key}'.")
        row.enabled = enabled
        self.admins.record_audit(
            admin_id=admin_id,
            action="provider_enabled" if enabled else "provider_paused",
            target_type="provider",
            target_id=key,
        )
        return row
