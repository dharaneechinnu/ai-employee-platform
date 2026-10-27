"""Usage: spend, estimated savings, free versus paid, per agent and per model.

The model is stubbed (see test_agent_schedule), so the calls that matter
for the sums are added straight to the log. What is checked: the figures
add up, savings never go negative and leave unpriced models out, the
reference can be changed, the range narrows what is counted, and one
person never sees another's usage.
"""

# The fixtures are imported from the agent schedule tests, which is what makes
# them visible here; naming them as arguments looks like redefinition to ruff.
# ruff: noqa: F811
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.task import LLMCall
from app.services.task_service import estimate_cost
from tests.integration.test_agent_schedule import (  # noqa: F401  (fixtures)
    AGENTS,
    Scripted,
    _new,
    _person,
    _run_task,
    queued,
    scripted,
)

USAGE = "/api/v1/me/usage"


async def _a_run(api: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    agent = (await api.post(AGENTS, json=_new(), headers=headers)).json()
    Scripted.call_first = None
    started = (await api.post(f"{AGENTS}/{agent['id']}/run", headers=headers)).json()
    done = await _run_task(uuid.UUID(started["task_id"]))
    return uuid.UUID(str(done["run_id"]))


async def _add_call(
    session: AsyncSession,
    owner_id: uuid.UUID,
    run_id: uuid.UUID,
    provider_key: str,
    model: str,
    prompt: int,
    output: int,
    *,
    free: bool = False,
    days_ago: int = 0,
) -> None:
    cost = Decimal(0) if free else estimate_cost(provider_key, model, prompt, output)
    session.add(
        LLMCall(
            run_id=run_id,
            owner_id=owner_id,
            provider_key=provider_key,
            model=model,
            prompt_tokens=prompt,
            output_tokens=output,
            cost_usd=cost,
            created_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )
    await session.commit()


async def _usage(api: AsyncClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = await api.get(USAGE, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


def _by_model(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["model"]: m for m in body["models"]}


async def test_a_person_with_no_runs_sees_an_empty_estimate(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    _, headers = await _person(api, session)
    body = await _usage(api, headers)
    assert body["estimate"] is True and body["range"] == "30d"
    assert body["models"] == [] and body["agents"] == []
    assert Decimal(body["total_cost_usd"]) == 0 and Decimal(body["saved_usd"]) == 0
    # Gemini is connected and priced, so there is something to compare with.
    assert body["reference"]["model"] == "gemini-2.0-flash"


async def test_spend_savings_and_shares_add_up(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    owner_id, headers = await _person(api, session)
    run_id = await _a_run(api, headers)
    # A free-tier Groq call, a paid Claude one and a model with no price.
    await _add_call(
        session, owner_id, run_id, "groq", "openai/gpt-oss-120b", 1_000_000, 100_000, free=True
    )
    await _add_call(session, owner_id, run_id, "anthropic", "claude-sonnet-5-5", 400_000, 40_000)
    await _add_call(session, owner_id, run_id, "custom", "my-local-model", 5_000, 500, free=True)

    body = await _usage(api, headers, reference="anthropic:claude-sonnet-5-5")
    models = _by_model(body)

    groq = models["openai/gpt-oss-120b"]
    assert groq["plan"] == "free" and Decimal(groq["cost_usd"]) == 0
    # The same tokens on Sonnet: 1M * $2 + 0.1M * $10 = $3.00, all of it saved.
    assert Decimal(groq["saved_usd"]) == Decimal("3")

    sonnet = models["claude-sonnet-5-5"]
    assert sonnet["plan"] == "paid" and sonnet["is_reference"] is True
    assert Decimal(sonnet["saved_usd"]) == 0
    assert Decimal(sonnet["cost_usd"]) == Decimal("1.2")  # 0.4M * 2 + 0.04M * 10

    local = models["my-local-model"]
    assert local["plan"] == "unknown" and local["saved_usd"] is None
    assert body["unpriced_calls"] == 1

    # The stubbed run's own Gemini call is priced and charged, so it is paid,
    # and it cost less than Sonnet would have: that is saved too, never negative.
    gemini = models["gemini-2.0-flash"]
    assert gemini["plan"] == "paid" and Decimal(gemini["saved_usd"]) > 0
    assert all(m["saved_usd"] is None or Decimal(m["saved_usd"]) >= 0 for m in body["models"])
    assert Decimal(body["saved_usd"]) == sum(
        Decimal(m["saved_usd"]) for m in body["models"] if m["saved_usd"] is not None
    )

    assert body["calls"] == 4 and body["runs"] == 1
    assert body["free"]["calls"] == 1 and body["paid"]["calls"] == 2
    assert body["unknown"]["calls"] == 1
    assert body["free"]["tokens"] == 1_100_000
    assert Decimal(body["total_cost_usd"]) == sum(Decimal(m["cost_usd"]) for m in body["models"])
    assert abs(sum(m["share"] for m in body["models"]) - 1) < 1e-9

    # One run, by the agent that started it.
    assert [a["name"] for a in body["agents"]] == ["Night Owl"]
    assert Decimal(body["agents"][0]["cost_usd"]) == Decimal(body["total_cost_usd"])


async def test_the_reference_defaults_to_the_priciest_connected_model_and_can_change(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    owner_id, headers = await _person(api, session)
    run_id = await _a_run(api, headers)
    await _add_call(
        session, owner_id, run_id, "groq", "openai/gpt-oss-20b", 1_000_000, 0, free=True
    )

    first = await _usage(api, headers)
    assert first["reference"]["model"] == "gemini-2.0-flash"
    assert first["reference_is_default"] is True

    connected = await api.post(
        "/api/v1/me/providers",
        json={"provider_key": "anthropic", "api_key": "test-key-wxyz9876"},
        headers=headers,
    )
    assert connected.status_code == 201, connected.text
    second = await _usage(api, headers)
    assert second["reference"]["provider_key"] == "anthropic"
    assert second["reference_is_default"] is True
    assert {"gemini-2.0-flash", "claude-opus-5-5"} <= {
        c["model"] for c in second["reference_choices"]
    }

    # Opus is $4 an input million; Gemini Flash is $0.10.
    assert Decimal(_by_model(second)["openai/gpt-oss-20b"]["saved_usd"]) == Decimal("4")
    chosen = await _usage(api, headers, reference="gemini:gemini-2.0-flash")
    assert chosen["reference_is_default"] is False
    assert Decimal(_by_model(chosen)["openai/gpt-oss-20b"]["saved_usd"]) == Decimal("0.1")

    for bad in ("anthropic:not-a-real-model", "nonsense", "custom:my-local-model"):
        refused = await api.get(USAGE, params={"reference": bad}, headers=headers)
        assert refused.status_code == 422, bad


async def test_the_range_narrows_what_is_counted(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    owner_id, headers = await _person(api, session)
    run_id = await _a_run(api, headers)
    await _add_call(session, owner_id, run_id, "groq", "openai/gpt-oss-20b", 1000, 0, days_ago=3)
    await _add_call(session, owner_id, run_id, "groq", "openai/gpt-oss-20b", 1000, 0, days_ago=20)
    await _add_call(session, owner_id, run_id, "groq", "openai/gpt-oss-20b", 1000, 0, days_ago=90)

    def groq_calls(body: dict[str, Any]) -> int:
        return int(_by_model(body).get("openai/gpt-oss-20b", {}).get("calls", 0))

    assert groq_calls(await _usage(api, headers, range="7d")) == 1
    assert groq_calls(await _usage(api, headers, range="30d")) == 2
    assert groq_calls(await _usage(api, headers, range="all")) == 3

    bad = await api.get(USAGE, params={"range": "year"}, headers=headers)
    assert bad.status_code == 422


async def test_one_person_cannot_see_anothers_usage(
    api: AsyncClient, session: AsyncSession, queued: list[uuid.UUID], scripted: None
) -> None:
    owner_id, headers = await _person(api, session)
    run_id = await _a_run(api, headers)
    await _add_call(session, owner_id, run_id, "anthropic", "claude-sonnet-5-5", 1_000_000, 0)

    from tests.integration.conftest import seed_person

    other = await seed_person(session, api, name="Ben")
    theirs = {"Authorization": f"Bearer {other.token}"}
    body = await _usage(api, theirs, range="all")
    assert body["models"] == [] and body["agents"] == [] and body["calls"] == 0
    assert Decimal(body["total_cost_usd"]) == 0 and body["reference"] is None

    # Nor can they borrow the other person's connections as a reference.
    mine = await _usage(api, headers, range="all")
    assert mine["calls"] == 2

    unsigned = await api.get(USAGE)
    assert unsigned.status_code in (401, 403)
