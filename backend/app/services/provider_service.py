"""BYOK provider configuration.

Each company brings its own API key. That is what makes the platform
viable on no budget: cost per customer is zero, and one heavy customer
cannot inflate anyone else's bill.

The key is write-only. After it is saved there is no code path that
returns the plaintext to any caller — not the company that set it, and
not the Platform Admin. `resolve_api_key` is the single exception, and
it is called only by the worker, immediately before a provider call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.providers import build_provider
from app.agent.providers.base import LLMError
from app.core.crypto import decrypt, encrypt
from app.core.errors import NotFoundError, ValidationError
from app.core.observability import get_logger
from app.db.models.provider import (
    ConnectionStatus,
    ProviderConfig,
    ProviderKind,
    SupportedProvider,
)

log = get_logger(__name__)


@dataclass(slots=True)
class ConnectedProvider:
    provider_key: str
    display_name: str
    key_last4: str
    status: ConnectionStatus
    last_tested_at: datetime | None
    last_error: str | None
    trains_on_data: bool
    default_model: str | None


class ProviderService:
    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        self.session = session
        self.org_id = org_id

    async def available(self) -> list[SupportedProvider]:
        result = await self.session.scalars(
            select(SupportedProvider)
            .where(SupportedProvider.enabled.is_(True), SupportedProvider.kind == ProviderKind.LLM)
            .order_by(SupportedProvider.display_name)
        )
        return list(result.all())

    async def _supported(self, provider_key: str) -> SupportedProvider:
        supported = await self.session.scalar(
            select(SupportedProvider).where(SupportedProvider.key == provider_key)
        )
        if supported is None or not supported.enabled:
            raise ValidationError(f"'{provider_key}' is not an available provider.")
        return supported

    async def connected(self) -> list[ConnectedProvider]:
        rows = await self.session.execute(
            select(ProviderConfig, SupportedProvider)
            .join(SupportedProvider, SupportedProvider.key == ProviderConfig.provider_key)
            .where(ProviderConfig.org_id == self.org_id)
            .order_by(SupportedProvider.display_name)
        )
        return [
            ConnectedProvider(
                provider_key=config.provider_key,
                display_name=supported.display_name,
                key_last4=config.key_last4,
                status=config.status,
                last_tested_at=config.last_tested_at,
                last_error=config.last_error,
                trains_on_data=supported.trains_on_data,
                default_model=supported.default_model,
            )
            for config, supported in rows.all()
        ]

    async def connect(self, *, provider_key: str, api_key: str) -> ProviderConfig:
        supported = await self._supported(provider_key)

        existing = await self.session.scalar(
            select(ProviderConfig).where(
                ProviderConfig.org_id == self.org_id,
                ProviderConfig.provider_key == provider_key,
            )
        )

        ciphertext = encrypt(api_key, scope=self.org_id)
        last4 = api_key[-4:] if len(api_key) >= 4 else "????"

        if existing is not None:
            # Replacing a key, not revealing one: there is no read path.
            existing.api_key_enc = ciphertext
            existing.key_last4 = last4
            existing.status = ConnectionStatus.UNTESTED
            existing.last_error = None
            config = existing
        else:
            config = ProviderConfig(
                org_id=self.org_id,
                provider_key=provider_key,
                api_key_enc=ciphertext,
                key_last4=last4,
            )
            self.session.add(config)

        await self.session.flush()
        log.info(
            "provider_connected",
            org_id=str(self.org_id),
            provider=provider_key,
            trains_on_data=supported.trains_on_data,
        )
        return config

    async def test(self, provider_key: str) -> ProviderConfig:
        """One cheap call, so a wrong key is caught now rather than as a
        mysterious task failure three days later."""
        config = await self._config(provider_key)
        supported = await self._supported(provider_key)

        api_key = decrypt(config.api_key_enc, scope=self.org_id)
        provider = build_provider(provider_key, api_key)

        try:
            await provider.check(supported.default_model or "gpt-4o-mini")
        except LLMError as exc:
            config.status = ConnectionStatus.FAILED
            config.last_error = exc.message[:500]
        else:
            config.status = ConnectionStatus.WORKING
            config.last_error = None

        config.last_tested_at = datetime.now(UTC)
        return config

    async def disconnect(self, provider_key: str) -> None:
        await self.session.delete(await self._config(provider_key))

    async def _config(self, provider_key: str) -> ProviderConfig:
        config = await self.session.scalar(
            select(ProviderConfig).where(
                ProviderConfig.org_id == self.org_id,
                ProviderConfig.provider_key == provider_key,
            )
        )
        if config is None:
            raise NotFoundError(f"'{provider_key}' is not connected.")
        return config

    async def resolve_api_key(self, provider_key: str) -> str:
        """Decrypt a key for an outbound call.

        The only place plaintext exists, called by the worker right
        before a provider request. The value never enters the model's
        context, so prompt injection has nothing to extract.
        """
        return decrypt((await self._config(provider_key)).api_key_enc, scope=self.org_id)

    async def model_choices(self) -> list[dict[str, object]]:
        """Models this company can actually pick, which means only the
        providers they have connected."""
        return [
            {
                "provider_key": c.provider_key,
                "display_name": c.display_name,
                "model": c.default_model,
                "status": c.status.value,
                "trains_on_data": c.trains_on_data,
            }
            for c in await self.connected()
            if c.default_model
        ]
