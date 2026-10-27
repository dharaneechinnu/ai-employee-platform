"""What the signed-in person's model calls cost, and what they saved.

Built from the `llm_calls` rows every run already leaves behind, so
nothing extra is stored. Free or paid is worked out when it is read, with
`plan_of` (the same rule History uses), and "saved" is worked out from the
price table and a reference model. Every figure is an estimate: with our
own keys we never see the provider's bill. Every query filters on the
owner.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.pricing import is_priced, plan_of, price_per_million
from app.core.errors import ValidationError
from app.db.models.agent import Agent
from app.db.models.provider import ProviderConfig, ProviderKind, SupportedProvider
from app.db.models.task import LLMCall, Run

RANGE_DAYS: dict[str, int | None] = {"7d": 7, "30d": 30, "all": None}
_MILLION = Decimal(1_000_000)


@dataclass(slots=True)
class ModelChoice:
    provider_key: str
    model: str
    provider_name: str


@dataclass(slots=True)
class ModelRow:
    provider_key: str
    provider_name: str
    model: str
    plan: str = "unknown"
    runs: int = 0
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    # None when the model has no price on file: unpriced, not zero.
    saved_usd: Decimal | None = None
    is_reference: bool = False
    share: float = 0.0

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens


@dataclass(slots=True)
class AgentRow:
    agent_id: uuid.UUID | None
    name: str
    runs: int = 0
    tokens: int = 0
    cost_usd: Decimal = Decimal(0)


@dataclass(slots=True)
class PlanShare:
    calls: int = 0
    tokens: int = 0
    cost_usd: Decimal = Decimal(0)


@dataclass(slots=True)
class Usage:
    range: str
    runs: int = 0
    calls: int = 0
    tokens: int = 0
    total_cost_usd: Decimal = Decimal(0)
    saved_usd: Decimal = Decimal(0)
    # Calls on models with no price: left out of "saved", not counted as zero.
    unpriced_calls: int = 0
    reference: ModelChoice | None = None
    reference_is_default: bool = True
    reference_choices: list[ModelChoice] = field(default_factory=list)
    plans: dict[str, PlanShare] = field(default_factory=dict)
    agents: list[AgentRow] = field(default_factory=list)
    models: list[ModelRow] = field(default_factory=list)


def _blended(provider_key: str, model: str) -> Decimal:
    price = price_per_million(provider_key, model)
    return price.input_usd + price.output_usd


class UsageService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    async def summary(self, range_key: str, reference: str | None) -> Usage:
        if range_key not in RANGE_DAYS:
            raise ValidationError("Pick 7d, 30d or all.")
        days = RANGE_DAYS[range_key]
        since = None if days is None else datetime.now(UTC) - timedelta(days=days)

        names = await self._provider_names()
        grouped = await self._by_model(since)
        usage = Usage(range=range_key)

        # Models worth offering as the reference: priced, and either
        # connected now or used in this range.
        choices: dict[tuple[str, str], ModelChoice] = {}
        for choice in await self._connected_models(names):
            choices[(choice.provider_key, choice.model)] = choice
        connected_default = max(
            choices.values(), key=lambda c: _blended(c.provider_key, c.model), default=None
        )
        for provider_key, model, *_ in grouped:
            if is_priced(provider_key, model):
                choices.setdefault(
                    (provider_key, model),
                    ModelChoice(provider_key, model, names.get(provider_key, provider_key)),
                )
        usage.reference_choices = sorted(
            choices.values(), key=lambda c: _blended(c.provider_key, c.model), reverse=True
        )

        ref = connected_default or (usage.reference_choices[0] if usage.reference_choices else None)
        if reference:
            provider_key, _, model = reference.partition(":")
            if not is_priced(provider_key, model):
                raise ValidationError("That model has no price on file, so it cannot be compared.")
            ref = choices.get((provider_key, model)) or ModelChoice(
                provider_key, model, names.get(provider_key, provider_key)
            )
            usage.reference_is_default = False
        usage.reference = ref
        ref_price = price_per_million(ref.provider_key, ref.model) if ref else None

        rows: dict[tuple[str, str], ModelRow] = {}
        plans = {"free": PlanShare(), "paid": PlanShare(), "unknown": PlanShare()}
        for provider_key, model, _charged, calls, runs, prompt, output, cost in grouped:
            row = rows.setdefault(
                (provider_key, model),
                ModelRow(provider_key, names.get(provider_key, provider_key), model),
            )
            row.calls += calls
            row.runs = max(row.runs, runs)
            row.prompt_tokens += prompt
            row.output_tokens += output
            row.cost_usd += cost
            share = plans[plan_of(provider_key, model, cost)]
            share.calls += calls
            share.tokens += prompt + output
            share.cost_usd += cost

        for row in rows.values():
            row.plan = plan_of(row.provider_key, row.model, row.cost_usd)
            if not is_priced(row.provider_key, row.model):
                usage.unpriced_calls += row.calls
            elif ref is not None and ref_price is not None:
                row.is_reference = (row.provider_key, row.model) == (ref.provider_key, ref.model)
                would = (
                    Decimal(row.prompt_tokens) * ref_price.input_usd
                    + Decimal(row.output_tokens) * ref_price.output_usd
                ) / _MILLION
                row.saved_usd = (
                    Decimal(0) if row.is_reference else max(Decimal(0), would - row.cost_usd)
                )
            usage.calls += row.calls
            usage.tokens += row.tokens
            usage.total_cost_usd += row.cost_usd
            usage.saved_usd += row.saved_usd or Decimal(0)
        for row in rows.values():
            row.share = row.calls / usage.calls if usage.calls else 0.0
        usage.models = sorted(rows.values(), key=lambda r: (-r.calls, r.model))
        usage.plans = plans
        usage.agents = await self._by_agent(since)
        usage.runs = sum(a.runs for a in usage.agents)
        return usage

    async def _provider_names(self) -> dict[str, str]:
        rows = await self.session.execute(
            select(SupportedProvider.key, SupportedProvider.display_name)
        )
        return {str(key): str(name) for key, name in rows.all()}

    async def _connected_models(self, names: dict[str, str]) -> list[ModelChoice]:
        rows = await self.session.execute(
            select(
                ProviderConfig.provider_key, ProviderConfig.model, SupportedProvider.default_model
            )
            .join(SupportedProvider, SupportedProvider.key == ProviderConfig.provider_key)
            .where(
                ProviderConfig.owner_id == self.owner_id,
                SupportedProvider.kind == ProviderKind.LLM,
            )
        )
        found = []
        for provider_key, chosen, default in rows.all():
            model = chosen or default
            if model and is_priced(provider_key, model):
                name = names.get(provider_key, provider_key)
                found.append(ModelChoice(provider_key, model, name))
        return found

    async def _by_model(
        self, since: datetime | None
    ) -> list[tuple[str, str, bool, int, int, int, int, Decimal]]:
        # Split on "was charged" so free and paid calls of one model stay apart.
        charged = LLMCall.cost_usd > 0
        query = (
            select(
                LLMCall.provider_key,
                LLMCall.model,
                charged,
                func.count(),
                func.count(func.distinct(LLMCall.run_id)),
                func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
                func.coalesce(func.sum(LLMCall.output_tokens), 0),
                func.coalesce(func.sum(LLMCall.cost_usd), 0),
            )
            .where(LLMCall.owner_id == self.owner_id)
            .group_by(LLMCall.provider_key, LLMCall.model, charged)
        )
        if since is not None:
            query = query.where(LLMCall.created_at >= since)
        return [
            (pk, m, bool(c), int(n), int(r), int(p), int(o), Decimal(cost))
            for pk, m, c, n, r, p, o, cost in (await self.session.execute(query)).all()
        ]

    async def _by_agent(self, since: datetime | None) -> list[AgentRow]:
        query = (
            select(
                Run.agent_id,
                Agent.name,
                func.count(func.distinct(LLMCall.run_id)),
                func.coalesce(func.sum(LLMCall.prompt_tokens + LLMCall.output_tokens), 0),
                func.coalesce(func.sum(LLMCall.cost_usd), 0),
            )
            .select_from(LLMCall)
            .join(Run, Run.id == LLMCall.run_id)
            .outerjoin(Agent, Agent.id == Run.agent_id)
            .where(LLMCall.owner_id == self.owner_id)
            .group_by(Run.agent_id, Agent.name)
        )
        if since is not None:
            query = query.where(LLMCall.created_at >= since)
        rows = [
            AgentRow(agent_id, name or "Assistant", int(runs), int(tokens), Decimal(cost))
            for agent_id, name, runs, tokens, cost in (await self.session.execute(query)).all()
        ]
        return sorted(rows, key=lambda r: (-r.cost_usd, -r.runs, r.name))
