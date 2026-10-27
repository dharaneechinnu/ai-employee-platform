"""Usage: what the signed-in person's models cost and what that saved.

Every figure is an estimate worked out from token counts and the price
table; the provider's own bill is the real one. "Saved" compares the
same tokens with a reference model, by default the priciest priced model
the person has connected, and can be pointed at another with `reference`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.v1.deps import ContextDep, SessionDep
from app.services.usage_service import ModelChoice, PlanShare, Usage, UsageService

router = APIRouter(prefix="/me/usage", tags=["usage"])

Plan = Literal["free", "paid", "unknown"]
RangeKey = Literal["7d", "30d", "all"]


class ModelChoiceOut(BaseModel):
    provider_key: str
    provider_name: str
    model: str


class PlanShareOut(BaseModel):
    calls: int
    tokens: int
    cost_usd: Decimal


class AgentSpendOut(BaseModel):
    # None is the assistant itself (a chat, not an agent).
    agent_id: uuid.UUID | None
    name: str
    runs: int
    tokens: int
    cost_usd: Decimal


class ModelUsageOut(BaseModel):
    provider_key: str
    provider_name: str
    model: str
    plan: Plan
    runs: int
    calls: int
    tokens: int
    cost_usd: Decimal
    # Null when the model has no price: unpriced, not zero.
    saved_usd: Decimal | None
    is_reference: bool
    # Share of all calls in the range, 0 to 1.
    share: float


class UsageOut(BaseModel):
    range: RangeKey
    # Always true: nothing here is a bill.
    estimate: bool = True
    runs: int
    calls: int
    tokens: int
    total_cost_usd: Decimal
    saved_usd: Decimal
    unpriced_calls: int
    reference: ModelChoiceOut | None
    reference_is_default: bool
    reference_choices: list[ModelChoiceOut]
    free: PlanShareOut
    paid: PlanShareOut
    unknown: PlanShareOut
    agents: list[AgentSpendOut]
    models: list[ModelUsageOut]


def _choice(c: ModelChoice) -> ModelChoiceOut:
    return ModelChoiceOut(provider_key=c.provider_key, provider_name=c.provider_name, model=c.model)


def _share(s: PlanShare) -> PlanShareOut:
    return PlanShareOut(calls=s.calls, tokens=s.tokens, cost_usd=s.cost_usd)


def _out(u: Usage, range_key: RangeKey) -> UsageOut:
    return UsageOut(
        range=range_key,
        runs=u.runs,
        calls=u.calls,
        tokens=u.tokens,
        total_cost_usd=u.total_cost_usd,
        saved_usd=u.saved_usd,
        unpriced_calls=u.unpriced_calls,
        reference=_choice(u.reference) if u.reference else None,
        reference_is_default=u.reference_is_default,
        reference_choices=[_choice(c) for c in u.reference_choices],
        free=_share(u.plans["free"]),
        paid=_share(u.plans["paid"]),
        unknown=_share(u.plans["unknown"]),
        agents=[
            AgentSpendOut(
                agent_id=a.agent_id, name=a.name, runs=a.runs, tokens=a.tokens, cost_usd=a.cost_usd
            )
            for a in u.agents
        ],
        models=[
            ModelUsageOut(
                provider_key=m.provider_key,
                provider_name=m.provider_name,
                model=m.model,
                plan=m.plan,
                runs=m.runs,
                calls=m.calls,
                tokens=m.tokens,
                cost_usd=m.cost_usd,
                saved_usd=m.saved_usd,
                is_reference=m.is_reference,
                share=m.share,
            )
            for m in u.models
        ],
    )


@router.get("", response_model=UsageOut, summary="What my models cost, and what that saved")
async def get_usage(
    ctx: ContextDep,
    session: SessionDep,
    range: Annotated[RangeKey, Query()] = "30d",
    reference: Annotated[
        str | None,
        Query(max_length=160, description="`provider:model` to compare against."),
    ] = None,
) -> UsageOut:
    return _out(await UsageService(session, ctx.owner_id).summary(range, reference), range)
