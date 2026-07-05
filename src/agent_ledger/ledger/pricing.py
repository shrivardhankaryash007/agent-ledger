"""Shared pricing-table loader. Used by every ingest source so cost math
stays consistent between batch (M0) and live (M1) capture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

PRICING_PATH = Path(__file__).parent / "pricing.yaml"


@dataclass(frozen=True)
class Price:
    """Per-thousand-token rates for one model."""

    input_rate: float
    output_rate: float


def load_pricing() -> dict[str, Price]:
    """Load and validate the versioned local pricing table."""

    raw: object = yaml.safe_load(PRICING_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("pricing table must be a mapping")
    root = cast("dict[object, object]", raw)
    sku_values = root.get("skus")
    if not isinstance(sku_values, dict):
        raise ValueError("pricing table must define a 'skus' mapping")

    prices: dict[str, Price] = {}
    for model, value in cast("dict[object, object]", sku_values).items():
        if not isinstance(model, str) or not isinstance(value, dict):
            raise ValueError("each pricing entry must map a model name to rates")
        rates = cast("dict[object, object]", value)
        input_rate = rates.get("input")
        output_rate = rates.get("output")
        if not isinstance(input_rate, (int, float)) or not isinstance(
            output_rate, (int, float)
        ):
            raise ValueError(f"pricing entry for {model!r} has invalid rates")
        prices[model] = Price(float(input_rate), float(output_rate))
    return prices


def cost_usd(
    model: str, in_tokens: int, out_tokens: int, prices: dict[str, Price]
) -> float:
    """Compute cost for a model already present in ``prices``.

    Raises KeyError if the model is not priced — callers decide the fallback
    (M0: hard failure: an unpriced historical call is a data-quality bug to
    fix, not a number to hide as zero. M1: fall through to litellm's own
    ``response_cost`` first; this is the last resort.).
    """

    price = prices[model]
    return in_tokens / 1000 * price.input_rate + out_tokens / 1000 * price.output_rate
