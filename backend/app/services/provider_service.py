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

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.providers import CUSTOM_PROVIDER, build_provider
from app.agent.providers.base import (
    LLMError,
    LLMProvider,
    ProviderAuthError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
)
from app.agent.providers.models import try_order
from app.agent.routing import (
    Candidate,
    Choice,
    Preference,
    TaskKind,
    classify_by_rules,
    explain,
    rank,
)
from app.agent.routing import strengths as routing_strengths
from app.core.crypto import decrypt, encrypt
from app.core.errors import NotFoundError, ValidationError
from app.core.observability import get_logger
from app.core.urls import check_service_url
from app.db.models.provider import (
    ConnectionStatus,
    ProviderConfig,
    ProviderKind,
    SupportedProvider,
)

log = get_logger(__name__)

# "Use whichever AI the company connected." `gemini-flash` is the old
# default, which was never a real Gemini model id, so it is treated the
# same way rather than sent to Google and rejected.
AUTO_MODEL = "auto"
_AUTO_ALIASES = {AUTO_MODEL, "gemini-flash", ""}

# When several providers are connected, the first working one in this
# order wins: the free tiers first.
_AUTO_PREFERENCE = [
    "gemini",
    "groq",
    "deepseek",
    "openrouter",
    "mistral",
    "openai",
    "anthropic",
    CUSTOM_PROVIDER,
]

MIN_KEY_LENGTH = 8


def split_model(model: str) -> tuple[str, str]:
    """Accept "gemini:gemini-2.0-flash" or a bare model name.

    A bare name defaults to Gemini, which is the documented starting
    provider, so existing configuration keeps working.
    """
    if ":" in model:
        provider_key, _, name = model.partition(":")
        return provider_key, name
    return "gemini", model


# How many models to try before giving up, and how long each may take.
MAX_MODEL_TRIES = 4
PROBE_SECONDS = 15.0


@dataclass(slots=True, frozen=True)
class Endpoint:
    """Where a provider is and how it is spoken to."""

    base_url: str | None
    api_format: str
    auth_header: str | None


@dataclass(slots=True)
class ModelTry:
    """One model auto-select tried, and what happened."""

    model: str
    ok: bool
    reason: str | None


@dataclass(slots=True)
class ConnectedProvider:
    provider_key: str
    display_name: str
    key_last4: str
    status: ConnectionStatus
    last_tested_at: datetime | None
    last_error: str | None
    trains_on_data: bool
    # What runs: the company's chosen model, else the provider's default.
    default_model: str | None
    # True when the company picked it, rather than taking the default.
    model_chosen: bool = False
    base_url: str | None = None
    # What Automatic routing sends to it, in plain words.
    strengths: list[str] | None = None


class ProviderService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

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
            .where(ProviderConfig.owner_id == self.owner_id)
            .order_by(SupportedProvider.display_name)
        )
        return [
            ConnectedProvider(
                provider_key=config.provider_key,
                display_name=config.label or supported.display_name,
                key_last4=config.key_last4,
                status=config.status,
                last_tested_at=config.last_tested_at,
                last_error=config.last_error,
                trains_on_data=supported.trains_on_data,
                default_model=config.model or supported.default_model,
                model_chosen=config.model is not None,
                base_url=config.base_url,
                strengths=routing_strengths(
                    config.provider_key, config.model or supported.default_model or ""
                ),
            )
            for config, supported in rows.all()
        ]

    async def connect(
        self,
        *,
        provider_key: str,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        label: str | None = None,
    ) -> ProviderConfig:
        supported = await self._supported(provider_key)
        api_key = api_key.strip()
        model = (model or "").strip() or None

        if provider_key == CUSTOM_PROVIDER:
            # Any OpenAI-compatible server: the company says where it is
            # and which model it serves. A key is optional, because a
            # self-hosted server often has none.
            if not base_url:
                raise ValidationError("Add your server's address, like https://llm.example.com/v1.")
            # The model is optional here: if the server lists its models
            # we find one for the person, and if not they are asked to type it.
            base_url = check_service_url(base_url, what="server")
            label = (label or "").strip()[:100] or None
        else:
            if len(api_key) < MIN_KEY_LENGTH:
                raise ValidationError("That API key looks too short. Paste the whole key.")
            base_url = None
            label = None

        existing = await self.session.scalar(
            select(ProviderConfig).where(
                ProviderConfig.owner_id == self.owner_id,
                ProviderConfig.provider_key == provider_key,
            )
        )

        ciphertext = encrypt(api_key, scope=self.owner_id)
        last4 = api_key[-4:] if len(api_key) >= 4 else ("none" if not api_key else "????")

        if existing is not None:
            # Replacing a key, not revealing one: there is no read path.
            existing.api_key_enc = ciphertext
            existing.key_last4 = last4
            existing.status = ConnectionStatus.UNTESTED
            existing.last_error = None
            existing.model = model
            existing.base_url = base_url
            existing.label = label
            config = existing
        else:
            config = ProviderConfig(
                owner_id=self.owner_id,
                provider_key=provider_key,
                api_key_enc=ciphertext,
                key_last4=last4,
                model=model,
                base_url=base_url,
                label=label,
            )
            self.session.add(config)

        await self.session.flush()
        log.info(
            "provider_connected",
            owner_id=str(self.owner_id),
            provider=provider_key,
            trains_on_data=supported.trains_on_data,
        )
        return config

    async def test(self, provider_key: str) -> ProviderConfig:
        """One cheap call, so a wrong key is caught now rather than as a
        mysterious task failure three days later."""
        config = await self._config(provider_key)
        supported = await self._supported(provider_key)
        provider = await self._provider(config)

        try:
            await provider.check(config.model or supported.default_model or "gpt-4o-mini")
        except LLMError as exc:
            config.status = ConnectionStatus.FAILED
            config.last_error = exc.message[:500]
        else:
            config.status = ConnectionStatus.WORKING
            config.last_error = None

        config.last_tested_at = datetime.now(UTC)
        return config

    async def set_model(self, provider_key: str, model: str | None) -> ProviderConfig:
        """Pick which model this provider runs. None goes back to the
        provider's default. The connection is marked untested, because
        a wrong model name fails just like a wrong key."""
        config = await self._config(provider_key)
        model = (model or "").strip() or None
        if model is None and provider_key == CUSTOM_PROVIDER:
            raise ValidationError("Your own server needs a model name.")
        if model != config.model:
            config.model = model
            config.status = ConnectionStatus.UNTESTED
            config.last_error = None
        return config

    async def list_models(self, provider_key: str) -> list[str]:
        """Ask the provider which models this key can use, chat models
        only: embedding, speech and moderation models cannot answer."""
        config = await self._config(provider_key)
        supported = await self._supported(provider_key)
        provider = await self._provider(config)
        try:
            ids = await provider.list_models()
        except LLMError as exc:
            raise ValidationError(f"Could not load the model list: {exc.message[:300]}") from exc
        return try_order(ids, config.model or supported.default_model)[:300]

    async def auto_select(
        self, provider_key: str, *, max_tries: int = MAX_MODEL_TRIES
    ) -> tuple[ProviderConfig, list[ModelTry]]:
        """Find a model this key can actually use, and switch to it.

        A model list says what exists, not what this plan may call, and
        a hardcoded default goes stale. So: list the key's chat models,
        most likely first, and make one tiny real call to each until one
        answers. A bad key stops it at once; a model the plan cannot
        reach just moves on to the next.
        """
        config = await self._config(provider_key)
        supported = await self._supported(provider_key)
        provider = await self._provider(config)
        current = config.model or supported.default_model

        try:
            ids = await provider.list_models()
        except LLMError:
            # No list (or no access to it): the default is all we have to try.
            ids = []
        order = try_order(ids, current)[:max_tries] or ([current] if current else [])

        tried: list[ModelTry] = []
        for model in order:
            try:
                await asyncio.wait_for(provider.check(model), timeout=PROBE_SECONDS)
            except ProviderAuthError as exc:
                config.status = ConnectionStatus.FAILED
                config.last_error = exc.message[:500]
                tried.append(ModelTry(model, False, "The provider rejected this key."))
                return config, tried
            except ProviderRateLimitError:
                # Reachable, just busy right now: the model exists for this key.
                tried.append(ModelTry(model, True, "Works, but is rate limited at the moment."))
                self._adopt(config, model, working=False)
                return config, tried
            except ProviderModelNotFoundError:
                tried.append(ModelTry(model, False, "Not available on this key's plan."))
            except (LLMError, TimeoutError) as exc:
                tried.append(
                    ModelTry(model, False, getattr(exc, "message", "Did not answer in time.")[:160])
                )
            else:
                tried.append(ModelTry(model, True, None))
                self._adopt(config, model, working=True)
                return config, tried
        return config, tried

    @staticmethod
    def _adopt(config: ProviderConfig, model: str, *, working: bool) -> None:
        config.model = model
        config.status = ConnectionStatus.WORKING if working else ConnectionStatus.UNTESTED
        config.last_error = None
        config.last_tested_at = datetime.now(UTC)

    async def _provider(self, config: ProviderConfig) -> LLMProvider:
        api_key = decrypt(config.api_key_enc, scope=self.owner_id)
        endpoint = await self.resolve_endpoint(config.provider_key)
        return build_provider(
            config.provider_key,
            api_key,
            base_url=endpoint.base_url,
            api_format=endpoint.api_format,
            auth_header=endpoint.auth_header,
        )

    async def resolve_api_key(self, provider_key: str) -> str:
        """Decrypt a key for an outbound call.

        The only place plaintext exists, called by the worker right
        before a provider request. The value never enters the model's
        context, so prompt injection has nothing to extract.
        """
        return decrypt((await self._config(provider_key)).api_key_enc, scope=self.owner_id)

    async def resolve_endpoint(self, provider_key: str) -> Endpoint:
        """How to reach this provider: the person's own address if they
        gave one (their own server), otherwise what the catalog row says.
        Read from data, so a provider added there needs no code."""
        config = await self._config(provider_key)
        row = await self.session.scalar(
            select(SupportedProvider).where(SupportedProvider.key == provider_key)
        )
        return Endpoint(
            base_url=config.base_url or (row.base_url if row else None),
            api_format=row.api_format if row else "openai",
            auth_header=row.auth_header if row else None,
        )

    async def disconnect(self, provider_key: str) -> None:
        await self.session.delete(await self._config(provider_key))

    async def _config(self, provider_key: str) -> ProviderConfig:
        config = await self.session.scalar(
            select(ProviderConfig).where(
                ProviderConfig.owner_id == self.owner_id,
                ProviderConfig.provider_key == provider_key,
            )
        )
        if config is None:
            raise NotFoundError(f"'{provider_key}' is not connected.")
        return config

    async def resolve_model(self, configured: str) -> tuple[str, str]:
        """The provider and model a run should use.

        An explicit "provider:model" is used as it is. "auto" picks the
        company's connected provider (a working one first) and that
        provider's default model, so a new company that connected only
        Groq does not fail on a Gemini default it never set up.
        """
        if configured.strip() not in _AUTO_ALIASES:
            return split_model(configured)

        candidates = [c for c in await self.connected() if c.default_model]
        if not candidates:
            raise NotFoundError("No AI provider is connected.")

        def rank(c: ConnectedProvider) -> tuple[int, int]:
            failed = 1 if c.status is ConnectionStatus.FAILED else 0
            order = (
                _AUTO_PREFERENCE.index(c.provider_key)
                if c.provider_key in _AUTO_PREFERENCE
                else len(_AUTO_PREFERENCE)
            )
            return failed, order

        best = min(candidates, key=rank)
        return best.provider_key, best.default_model or ""

    async def candidates(self) -> list[Candidate]:
        """Every connected AI, with the model this person picked for it."""
        return [
            Candidate(
                provider_key=c.provider_key,
                model=c.default_model,
                display_name=c.display_name,
                failed=c.status is ConnectionStatus.FAILED,
            )
            for c in await self.connected()
            if c.default_model
        ]

    async def route(
        self,
        configured: str,
        *,
        text: str,
        preference: Preference = Preference.BALANCED,
        history_chars: int = 0,
        classify: Callable[[list[Candidate]], Awaitable[TaskKind]] | None = None,
    ) -> list[Choice]:
        """Which AI should do this task, best first, the rest as fallbacks.

        A pinned "provider:model" is used as it is, with no fallback:
        the person chose it. "Automatic" decides the kind of task (rules
        first; `classify` only when they cannot tell and there is a real
        choice to make) and ranks the connected AIs for it.
        """
        if configured.strip() not in _AUTO_ALIASES:
            provider_key, model = split_model(configured)
            name = next(
                (c.display_name for c in await self.connected() if c.provider_key == provider_key),
                provider_key,
            )
            return [
                Choice(
                    provider_key=provider_key,
                    model=model,
                    display_name=name,
                    kind=TaskKind.GENERAL,
                    preference=preference,
                    reason="the AI you chose",
                )
            ]

        candidates = await self.candidates()
        if not candidates:
            raise NotFoundError("No AI is connected.")

        kind = classify_by_rules(text, history_chars=history_chars)
        if kind is None:
            kind = (
                await classify(candidates)
                if classify is not None and len(candidates) > 1
                else TaskKind.GENERAL
            )

        ranked = rank(candidates, kind, preference)
        if not ranked:
            raise NotFoundError(
                "Private only uses your own server, and none is connected. "
                "Connect one under AI Providers, or choose another preference."
            )
        return [
            Choice(
                provider_key=c.provider_key,
                model=c.model,
                display_name=c.display_name,
                kind=kind,
                preference=preference,
                reason=explain(c, kind, preference, len(ranked) - 1)
                if i == 0
                else "next best, if the first is unavailable",
            )
            for i, c in enumerate(ranked)
        ]

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
