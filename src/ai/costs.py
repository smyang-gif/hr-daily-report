"""Conservative per-run API cost estimates for credit runway alerts."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .tokens import TokenUsageSnapshot


_ONE_MILLION = Decimal(1_000_000)

# USD per million tokens. Keep aliases and dated ids explicit so a model
# migration cannot silently inherit the wrong price.
MODEL_PRICING_USD: dict[str, tuple[Decimal, Decimal]] = {
    "anthropic/claude-haiku-4-5": (Decimal("1"), Decimal("5")),
    "anthropic/claude-haiku-4-5-20251001": (Decimal("1"), Decimal("5")),
    "anthropic/claude-sonnet-5": (Decimal("2"), Decimal("10")),
}


def build_usage_record(
    snapshot: TokenUsageSnapshot,
    *,
    date: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a serializable usage record and estimate its priced cost."""
    generated_at = generated_at or datetime.now(timezone.utc)
    total_cost = Decimal("0")
    unknown_models: list[str] = []
    models: list[dict[str, Any]] = []

    for key, usage in sorted(snapshot.per_model.items()):
        provider, model = key.split("/", 1)
        pricing = MODEL_PRICING_USD.get(key)
        estimated_cost: Decimal | None = None
        if pricing is None:
            unknown_models.append(key)
        else:
            input_price, output_price = pricing
            estimated_cost = (
                Decimal(usage.input_tokens) * input_price
                + Decimal(usage.output_tokens) * output_price
            ) / _ONE_MILLION
            total_cost += estimated_cost

        models.append(
            {
                "provider": provider,
                "model": model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "estimated_cost_usd": (
                    format(estimated_cost, ".6f")
                    if estimated_cost is not None
                    else None
                ),
            }
        )

    return {
        "date": date,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "input_tokens": snapshot.total_input_tokens,
        "output_tokens": snapshot.total_output_tokens,
        "estimated_cost_usd": format(total_cost, ".6f"),
        "unknown_price_models": unknown_models,
        "models": models,
    }
