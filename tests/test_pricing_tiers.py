"""Packet AL-A acceptance: long-prompt pricing tiers (written to fail first).

Some models bill a higher rate once the *prompt* passes a size threshold (e.g.
5x above 100K prompt tokens). The ledger priced every call at the base rate, so
long calls were understated. These tests pin the contract; nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_ledger.ledger import pricing
from agent_ledger.ledger.pricing import Price, cost_usd, load_pricing

BASE = Price(
    input_rate=0.1,
    output_rate=0.5,
    cache_read_rate=0.01,
    cache_write_rate=0.125,
    long_prompt_threshold=100_000,
    long_input_rate=0.5,
    long_output_rate=2.5,
    long_cache_read_rate=0.05,
    long_cache_write_rate=0.625,
)
PLAIN = Price(
    input_rate=0.1, output_rate=0.5, cache_read_rate=0.01, cache_write_rate=0.125
)


def test_price_without_a_tier_is_unchanged() -> None:
    assert PLAIN.long_prompt_threshold is None
    # 200_000 fresh in, 1_000 out: base rates only, however long the prompt.
    assert cost_usd("m", 200_000, 1_000, {"m": PLAIN}) == pytest.approx(
        200_000 / 1000 * 0.1 + 1_000 / 1000 * 0.5
    )


def test_prompt_at_or_below_the_threshold_uses_base_rates() -> None:
    # prompt = in_tokens + cache_read_tokens = 100_000, which is NOT above the threshold
    expected = 60_000 / 1000 * 0.1 + 40_000 / 1000 * 0.01 + 2_000 / 1000 * 0.5
    got = cost_usd("m", 60_000, 2_000, {"m": BASE}, cache_read_tokens=40_000)
    assert got == pytest.approx(expected)


def test_prompt_above_the_threshold_uses_every_long_rate() -> None:
    # prompt = 70_000 + 40_000 = 110_000 > 100_000.
    # in_tokens includes 10_000 cache writes.
    expected = (
        (70_000 - 10_000) / 1000 * 0.5
        + 10_000 / 1000 * 0.625
        + 40_000 / 1000 * 0.05
        + 3_000 / 1000 * 2.5
    )
    got = cost_usd(
        "m",
        70_000,
        3_000,
        {"m": BASE},
        cache_read_tokens=40_000,
        cache_write_tokens=10_000,
    )
    assert got == pytest.approx(expected)


def test_one_hour_cache_writes_use_twice_the_effective_input_rate() -> None:
    expected = (
        (70_000 - 10_000) / 1000 * 0.1
        + 6_000 / 1000 * 0.125
        + 4_000 / 1000 * 0.2
        + 3_000 / 1000 * 0.5
    )
    got = cost_usd(
        "m",
        70_000,
        3_000,
        {"m": BASE},
        cache_write_tokens=10_000,
        cache_write_1h_tokens=4_000,
    )
    assert got == pytest.approx(expected)


def test_one_hour_cache_writes_use_long_effective_input_rate() -> None:
    expected = (
        (70_000 - 10_000) / 1000 * 0.5
        + 6_000 / 1000 * 0.625
        + 4_000 / 1000 * 1.0
        + 40_000 / 1000 * 0.05
        + 3_000 / 1000 * 2.5
    )
    got = cost_usd(
        "m",
        70_000,
        3_000,
        {"m": BASE},
        cache_read_tokens=40_000,
        cache_write_tokens=10_000,
        cache_write_1h_tokens=4_000,
    )
    assert got == pytest.approx(expected)


def test_one_hour_cache_write_count_must_be_subset_of_all_writes() -> None:
    with pytest.raises(ValueError, match="subset"):
        cost_usd(
            "m",
            100,
            0,
            {"m": PLAIN},
            cache_write_tokens=10,
            cache_write_1h_tokens=11,
        )


def test_one_token_over_the_threshold_switches_tier() -> None:
    at = cost_usd("m", 100_000, 0, {"m": BASE})
    over = cost_usd("m", 100_001, 0, {"m": BASE})
    assert at == pytest.approx(100_000 / 1000 * 0.1)
    assert over == pytest.approx(100_001 / 1000 * 0.5)


def _load_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> dict[str, Price]:
    table = tmp_path / "pricing.yaml"
    table.write_text("version: 4\nskus:\n" + body, encoding="utf-8")
    monkeypatch.setattr(pricing, "PRICING_PATH", table)
    return load_pricing()


def test_loader_reads_a_complete_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prices = _load_from(
        tmp_path,
        monkeypatch,
        "  m: { input: 0.0001, output: 0.0005, long_prompt_threshold: 100000,"
        " long_input: 0.0005, long_output: 0.0025 }\n",
    )
    price = prices["m"]
    assert price.long_prompt_threshold == 100_000
    assert price.long_input_rate == pytest.approx(0.0005)
    assert price.long_output_rate == pytest.approx(0.0025)
    # Omitted long cache rates follow the same multipliers as the base rates.
    assert price.long_cache_read_rate == pytest.approx(
        0.0005 * pricing.CACHE_READ_MULTIPLIER
    )
    assert price.long_cache_write_rate == pytest.approx(
        0.0005 * pricing.CACHE_WRITE_MULTIPLIER
    )


def test_loader_leaves_untiered_models_untiered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prices = _load_from(tmp_path, monkeypatch, "  m: { input: 0.001, output: 0.002 }\n")
    assert prices["m"].long_prompt_threshold is None
    assert prices["m"].long_input_rate is None


@pytest.mark.parametrize(
    "fields",
    [
        "long_prompt_threshold: 100000",
        "long_prompt_threshold: 100000, long_input: 0.0005",
        "long_input: 0.0005, long_output: 0.0025",
    ],
)
def test_loader_rejects_a_partial_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fields: str
) -> None:
    with pytest.raises(ValueError, match="tier"):
        _load_from(
            tmp_path, monkeypatch, f"  m: {{ input: 0.001, output: 0.002, {fields} }}\n"
        )


def test_loader_rejects_a_non_numeric_tier_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="tier"):
        _load_from(
            tmp_path,
            monkeypatch,
            "  m: { input: 0.001, output: 0.002, long_prompt_threshold: lots,"
            " long_input: 0.005, long_output: 0.01 }\n",
        )


def test_the_shipped_table_still_loads() -> None:
    assert "claude-sonnet-5-5" in load_pricing()


def test_the_shipped_table_prices_a_long_haiku_call_at_the_long_rate() -> None:
    prices = load_pricing()
    haiku = prices["claude-haiku-5-5"]
    assert haiku.long_prompt_threshold == 100_000
    short = cost_usd("claude-haiku-5-5", 50_000, 0, prices)
    long_ = cost_usd("claude-haiku-5-5", 150_000, 0, prices)
    assert short == pytest.approx(50_000 / 1000 * 0.0001)
    assert long_ == pytest.approx(150_000 / 1000 * 0.0005)
