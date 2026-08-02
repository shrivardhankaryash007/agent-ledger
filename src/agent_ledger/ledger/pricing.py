"""Shared pricing-table loader. Used by every ingest source so cost math
stays consistent between batch (M0) and live (M1) capture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

PRICING_PATH = Path(__file__).parent / "pricing.yaml"


# Anthropic's published multipliers against the base input rate. Used only
# when a SKU's pricing entry omits explicit `cache_read`/`cache_write` rates,
# so adding cache accounting did not require re-stating rates for every
# already-priced historical SKU.
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


@dataclass(frozen=True)
class Price:
    """Per-thousand-token rates for one model."""

    input_rate: float
    output_rate: float
    cache_read_rate: float = 0.0
    cache_write_rate: float = 0.0


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
        cache_read = rates.get("cache_read")
        cache_write = rates.get("cache_write")
        if cache_read is not None and not isinstance(cache_read, (int, float)):
            raise ValueError(f"pricing entry for {model!r} has an invalid cache_read")
        if cache_write is not None and not isinstance(cache_write, (int, float)):
            raise ValueError(f"pricing entry for {model!r} has an invalid cache_write")
        prices[model] = Price(
            input_rate=float(input_rate),
            output_rate=float(output_rate),
            cache_read_rate=(
                float(cache_read)
                if cache_read is not None
                else float(input_rate) * CACHE_READ_MULTIPLIER
            ),
            cache_write_rate=(
                float(cache_write)
                if cache_write is not None
                else float(input_rate) * CACHE_WRITE_MULTIPLIER
            ),
        )
    return prices


def cost_usd(
    model: str,
    in_tokens: int,
    out_tokens: int,
    prices: dict[str, Price],
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Compute cost for a model already present in ``prices``.

    ``in_tokens`` follows the ``CallRecord`` convention: it already *includes*
    ``cache_write_tokens``. Cache writes are therefore re-rated out of the
    base input rate rather than added on top, so passing them can never
    double-charge. ``cache_read_tokens`` is separate volume and is added.

    The cache keyword arguments default to ``0``, which reproduces the exact
    pre-v3 result — existing callers (M1 live capture) keep working unchanged
    and simply keep reporting a cache-blind number until they are updated.

    Args:
        model: Pricing-table key, e.g. ``"claude-sonnet-5"``.
        in_tokens: Fresh input plus cache-write tokens.
        out_tokens: Generated tokens.
        prices: Table from :func:`load_pricing`.
        cache_read_tokens: Tokens served from an existing prompt cache.
        cache_write_tokens: Subset of ``in_tokens`` written into the cache.

    Returns:
        Cost in USD.

    Raises:
        KeyError: If the model is not priced — callers decide the fallback
            (M0: hard failure; an unpriced historical call is a data-quality
            bug to fix, not a number to hide as zero. M1: fall through to
            litellm's own ``response_cost`` first; this is the last resort.).

    Example:
        >>> prices = {"m": Price(3.0 / 1000, 15.0 / 1000, 0.3 / 1000, 3.75 / 1000)}
        >>> round(cost_usd("m", 1000, 0, prices, cache_read_tokens=1000), 6)
        0.0033
    """

    price = prices[model]
    fresh_in_tokens = max(in_tokens - cache_write_tokens, 0)
    return (
        fresh_in_tokens / 1000 * price.input_rate
        + cache_write_tokens / 1000 * price.cache_write_rate
        + cache_read_tokens / 1000 * price.cache_read_rate
        + out_tokens / 1000 * price.output_rate
    )
