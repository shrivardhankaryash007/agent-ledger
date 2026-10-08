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
    long_prompt_threshold: int | None = None
    long_input_rate: float | None = None
    long_output_rate: float | None = None
    long_cache_read_rate: float | None = None
    long_cache_write_rate: float | None = None


_Tier = tuple[int | None, float | None, float | None, float | None, float | None]


def _tier_rate(model: str, key: str, value: object) -> float:
    """Coerce one long-prompt tier rate to ``float``.

    Args:
        model: Pricing-table key, used in the error message.
        key: The YAML key being read, used in the error message.
        value: The raw value from ``pricing.yaml``.

    Returns:
        The rate as a float.

    Raises:
        ValueError: If ``value`` is not a real number.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"pricing entry for {model!r} has an invalid tier value for {key!r}"
        )
    return float(value)


def _load_tier(model: str, rates: dict[object, object]) -> _Tier:
    """Read one SKU's optional long-prompt tier.

    ``long_prompt_threshold``, ``long_input`` and ``long_output`` must appear
    together or not at all. The cache rates are optional; when omitted they
    follow the same multipliers as the base cache rates.

    Args:
        model: Pricing-table key, used in error messages.
        rates: The raw mapping for this SKU from ``pricing.yaml``.

    Returns:
        ``(threshold, input, output, cache_read, cache_write)``, all ``None``
        when the SKU has no tier.

    Raises:
        ValueError: If the tier is partially specified or a tier value is invalid.
    """
    threshold_raw = rates.get("long_prompt_threshold")
    input_raw = rates.get("long_input")
    output_raw = rates.get("long_output")
    cache_read_raw = rates.get("long_cache_read")
    cache_write_raw = rates.get("long_cache_write")
    if threshold_raw is None or input_raw is None or output_raw is None:
        partial_values = (
            threshold_raw,
            input_raw,
            output_raw,
            cache_read_raw,
            cache_write_raw,
        )
        if any(value is not None for value in partial_values):
            raise ValueError(
                f"pricing entry for {model!r} has an incomplete tier: "
                "long_prompt_threshold, long_input and long_output must all be set"
            )
        return None, None, None, None, None
    if isinstance(threshold_raw, bool) or not isinstance(threshold_raw, int):
        raise ValueError(f"pricing entry for {model!r} has an invalid tier threshold")
    long_input = _tier_rate(model, "long_input", input_raw)
    long_output = _tier_rate(model, "long_output", output_raw)
    long_cache_read = (
        _tier_rate(model, "long_cache_read", cache_read_raw)
        if cache_read_raw is not None
        else long_input * CACHE_READ_MULTIPLIER
    )
    long_cache_write = (
        _tier_rate(model, "long_cache_write", cache_write_raw)
        if cache_write_raw is not None
        else long_input * CACHE_WRITE_MULTIPLIER
    )
    return threshold_raw, long_input, long_output, long_cache_read, long_cache_write


def _rates_for_prompt(
    price: Price, prompt_tokens: int
) -> tuple[float, float, float, float]:
    """Select the base or long-prompt rates for one call.

    The long tier applies only when ``prompt_tokens`` is strictly above the
    SKU's threshold and all four long rates are set. Otherwise the base rates
    are returned, exactly as before tiers existed.

    Args:
        price: The model's price entry.
        prompt_tokens: Prompt size, ``in_tokens + cache_read_tokens``.

    Returns:
        ``(input, output, cache_read, cache_write)`` rates per thousand tokens.
    """
    threshold = price.long_prompt_threshold
    long_input = price.long_input_rate
    long_output = price.long_output_rate
    long_cache_read = price.long_cache_read_rate
    long_cache_write = price.long_cache_write_rate
    if (
        threshold is not None
        and prompt_tokens > threshold
        and long_input is not None
        and long_output is not None
        and long_cache_read is not None
        and long_cache_write is not None
    ):
        return long_input, long_output, long_cache_read, long_cache_write
    return (
        price.input_rate,
        price.output_rate,
        price.cache_read_rate,
        price.cache_write_rate,
    )


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
        (
            long_threshold,
            long_input,
            long_output,
            long_cache_read,
            long_cache_write,
        ) = _load_tier(model, rates)
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
            long_prompt_threshold=long_threshold,
            long_input_rate=long_input,
            long_output_rate=long_output,
            long_cache_read_rate=long_cache_read,
            long_cache_write_rate=long_cache_write,
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
    input_rate, output_rate, cache_read_rate, cache_write_rate = _rates_for_prompt(
        price, in_tokens + cache_read_tokens
    )
    return (
        fresh_in_tokens / 1000 * input_rate
        + cache_write_tokens / 1000 * cache_write_rate
        + cache_read_tokens / 1000 * cache_read_rate
        + out_tokens / 1000 * output_rate
    )
