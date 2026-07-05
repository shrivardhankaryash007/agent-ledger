"""M2 acceptance test (docs/architecture.md).

Verifies the counterfactual replay computes an honest CEILING, not a
recommendation: real cost math, a hard-coded not-modeled bucket for
anything outside the Anthropic downgrade path, and a share metric that
lets a caller check the >=... calls-modeled kill criterion themselves
rather than trusting a hidden default.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.pricing import Price
from agent_ledger.policy.replay import downgraded_cost, replay

PRICES = {
    "claude-opus-4-8": Price(input_rate=0.005, output_rate=0.025),
    "claude-sonnet-5": Price(input_rate=0.003, output_rate=0.015),
    "claude-haiku-4-5-20251001": Price(input_rate=0.001, output_rate=0.005),
}


def _record(
    *,
    capability_class: str,
    vendor: str,
    model_sku: str,
    in_tokens: int,
    out_tokens: int,
    cost_usd: float,
) -> CallRecord:
    return CallRecord(
        ts=datetime(2026, 7, 5, tzinfo=UTC),
        session_id="s1",
        project="workspace",
        model_sku=model_sku,
        capability_class=capability_class,
        vendor=vendor,
        in_tokens=in_tokens,
        out_tokens=out_tokens,
        cost_usd=cost_usd,
        calls=1,
    )


def test_frontier_deep_downgrades_to_coding_strong_rate() -> None:
    record = _record(
        capability_class="frontier_deep",
        vendor="anthropic",
        model_sku="claude-opus-4-8",
        in_tokens=1000,
        out_tokens=1000,
        cost_usd=1000 / 1000 * 0.005 + 1000 / 1000 * 0.025,  # 0.030
    )
    alt = downgraded_cost(record, PRICES)
    assert alt == pytest.approx(
        1000 / 1000 * 0.003 + 1000 / 1000 * 0.015
    )  # sonnet rate


def test_local_capability_class_has_no_downgrade() -> None:
    record = _record(
        capability_class="local_fast",
        vendor="ollama",
        model_sku="qwen2.5-coder:14b",
        in_tokens=1000,
        out_tokens=1000,
        cost_usd=0.0,
    )
    assert downgraded_cost(record, PRICES) is None


def test_replay_aggregates_modeled_and_not_modeled_separately() -> None:
    modeled = _record(
        capability_class="frontier_deep",
        vendor="anthropic",
        model_sku="claude-opus-4-8",
        in_tokens=1000,
        out_tokens=1000,
        cost_usd=0.030,
    )
    not_modeled = _record(
        capability_class="frontier_deep",
        vendor="openai",  # only anthropic has a modeled downgrade path
        model_sku="gpt-5.5",
        in_tokens=1000,
        out_tokens=1000,
        cost_usd=0.035,
    )

    result = replay([modeled, not_modeled], PRICES)

    assert result.calls_modeled == 1
    assert result.calls_not_modeled == 1
    assert result.modeled_share == pytest.approx(0.5)
    assert result.actual_cost_usd == pytest.approx(0.065)
    assert result.not_modeled_cost_usd == pytest.approx(0.035)
    # ceiling savings only reflects the modeled call: 0.030 actual -> sonnet-rate alt
    expected_downgraded = 1000 / 1000 * 0.003 + 1000 / 1000 * 0.015
    assert result.downgraded_cost_usd == pytest.approx(expected_downgraded)
    assert result.ceiling_savings_usd == pytest.approx(0.065 - expected_downgraded)
