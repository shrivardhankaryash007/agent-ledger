"""M2 — counterfactual replay. Pure functions, no I/O (per module boundary
rule in docs/architecture.md).

WHAT THIS COMPUTES, PRECISELY (read before trusting the number):
For each historical CallRecord, "what would this exact call have cost at
the next-cheaper capability tier, holding token counts fixed?" Summed
across all records, that is a THEORETICAL CEILING on savings, not a
recommendation. It answers a cost question, not a quality question.

WHY IT STOPS THERE (the honest limit, not an oversight):
MODEL-ROUTING.md's routing table is keyed on task type (ambiguity, blast
radius, domain risk, novelty) — none of which a token-count ledger record
captures. Recovering task type would mean re-reading and re-judging every
historical call individually. This module does not do that, and does not
pretend to: it assumes every call could have been safely downgraded, which
ADR 0029 already disproves for a meaningful share of coding_strong work
(local tiers are unsafe for autonomous multi-file execution). The ceiling
this produces is deliberately an upper bound — the real, defensible number
is smaller by an unknown amount. Report it as a ceiling, always, never as
"the savings."

Downgrade path modeled (Anthropic only — the vendor nearly all real
historical spend in this workspace is on; other vendors' calls are counted
under `not_modeled_cost_usd` rather than guessed):
    frontier_deep  -> coding_strong   (opus/fable rate -> sonnet rate)
    coding_strong  -> fast_small      (sonnet rate -> haiku rate)
    fast_small     -> local_fast      (haiku rate -> $0, local Ollama)
    general_strong -> fast_small      (same as coding_strong's next step)
local_* classes have no cheaper tier modeled (already the floor).
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.pricing import Price

DOWNGRADE_TIER: dict[str, str] = {
    "frontier_deep": "coding_strong",
    "general_strong": "fast_small",
    "coding_strong": "fast_small",
    "fast_small": "local_fast",
}

# (vendor, capability_class) -> representative SKU whose rate stands in for
# that tier. Anthropic-only by design (see module docstring). Add a vendor
# here only once its own tier SKUs are confirmed in pricing.yaml — do not
# guess a stand-in.
REPRESENTATIVE_SKU: dict[tuple[str, str], str | None] = {
    ("anthropic", "coding_strong"): "claude-sonnet-5",
    ("anthropic", "fast_small"): "claude-haiku-4-5-20251001",
    ("anthropic", "local_fast"): None,  # $0 — no SKU lookup needed
}


@dataclass
class ReplayResult:
    """Aggregate replay outcome. Every field is a real, disclosed number —
    no single "savings" figure is reported without its ceiling caveat."""

    calls_modeled: int = 0
    calls_not_modeled: int = 0
    actual_cost_usd: float = 0.0
    downgraded_cost_usd: float = 0.0
    not_modeled_cost_usd: float = 0.0

    @property
    def ceiling_savings_usd(self) -> float:
        return self.actual_cost_usd - self.downgraded_cost_usd

    @property
    def modeled_share(self) -> float:
        total = self.calls_modeled + self.calls_not_modeled
        return self.calls_modeled / total if total else 0.0


def downgraded_cost(record: CallRecord, prices: dict[str, Price]) -> float | None:
    """Cost this record's tokens would have cost at the next-cheaper tier.

    Returns None when no downgrade path is modeled for this
    (vendor, capability_class) pair — caller must count it under
    not_modeled, never silently as zero savings.
    """

    next_tier = DOWNGRADE_TIER.get(record.capability_class)
    if next_tier is None:
        return None
    key = (record.vendor, next_tier)
    if key not in REPRESENTATIVE_SKU:
        return None
    sku = REPRESENTATIVE_SKU[key]
    if sku is None:
        return 0.0
    price = prices.get(sku)
    if price is None:
        return None
    return (
        record.in_tokens / 1000 * price.input_rate
        + record.out_tokens / 1000 * price.output_rate
    )


def replay(records: list[CallRecord], prices: dict[str, Price]) -> ReplayResult:
    """Run the counterfactual replay over every record. See module docstring
    for exactly what this does and does not claim."""

    result = ReplayResult()
    for record in records:
        result.actual_cost_usd += record.cost_usd
        alt_cost = downgraded_cost(record, prices)
        if alt_cost is None:
            result.calls_not_modeled += 1
            result.not_modeled_cost_usd += record.cost_usd
        else:
            result.calls_modeled += 1
            result.downgraded_cost_usd += alt_cost
    return result


__all__ = [
    "DOWNGRADE_TIER",
    "REPRESENTATIVE_SKU",
    "ReplayResult",
    "downgraded_cost",
    "replay",
]
