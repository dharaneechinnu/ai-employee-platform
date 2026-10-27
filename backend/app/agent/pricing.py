"""Model prices, in USD per million tokens.

These change often. Verify before quoting them to anyone, and treat
every number derived from this table as an estimate — with BYOK we
never see the customer's actual invoice.

An unknown model costs 0 rather than raising. A missing price entry
should not fail a run that otherwise succeeded; it shows up as a zero
in the cost column, which is visible and fixable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Price:
    input_usd: Decimal
    output_usd: Decimal


_ZERO = Price(Decimal("0"), Decimal("0"))

PRICING: dict[tuple[str, str], Price] = {
    # Gemini
    ("gemini", "gemini-2.0-flash"): Price(Decimal("0.10"), Decimal("0.40")),
    ("gemini", "gemini-2.5-flash"): Price(Decimal("0.30"), Decimal("2.50")),
    ("gemini", "gemini-2.5-pro"): Price(Decimal("1.25"), Decimal("10.00")),
    # Groq. The gpt-oss pair is what a free key can reach; the Llama
    # models moved behind a sales contact and answer "model_not_found"
    # to everyone else.
    ("groq", "openai/gpt-oss-20b"): Price(Decimal("0.075"), Decimal("0.30")),
    ("groq", "openai/gpt-oss-120b"): Price(Decimal("0.15"), Decimal("0.60")),
    ("groq", "llama-3.3-70b-versatile"): Price(Decimal("0.59"), Decimal("0.79")),
    ("groq", "llama-3.1-8b-instant"): Price(Decimal("0.05"), Decimal("0.08")),
    # OpenAI
    ("openai", "gpt-4o-mini"): Price(Decimal("0.15"), Decimal("0.60")),
    ("openai", "gpt-4o"): Price(Decimal("2.50"), Decimal("10.00")),
    # DeepSeek
    ("deepseek", "deepseek-chat"): Price(Decimal("0.27"), Decimal("1.10")),
    # Anthropic (Claude)
    ("anthropic", "claude-opus-5-5"): Price(Decimal("4.00"), Decimal("20.00")),
    ("anthropic", "claude-sonnet-5-5"): Price(Decimal("2.00"), Decimal("10.00")),
    ("anthropic", "claude-haiku-5-5"): Price(Decimal("0.10"), Decimal("0.50")),
    # Mistral
    ("mistral", "mistral-small-latest"): Price(Decimal("0.10"), Decimal("0.30")),
}


def price_per_million(provider_key: str, model: str) -> Price:
    return PRICING.get((provider_key, model), _ZERO)


def is_priced(provider_key: str, model: str) -> bool:
    """So a UI can mark a cost as "unknown" rather than showing $0.00
    as if the call were free."""
    return (provider_key, model) in PRICING


def plan_of(provider_key: str, model: str, cost_usd: Decimal) -> str:
    """ "paid", "free" or "unknown" for one model call.

    Until a connection says which plan it is on, the price table is all
    there is: a priced model that was charged for is paid, a priced one
    that cost nothing is free, and a model with no price is "unknown"
    rather than free.
    """
    if not is_priced(provider_key, model):
        return "unknown"
    return "paid" if cost_usd > 0 else "free"
