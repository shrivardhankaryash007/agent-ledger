"""Pre-registered success check for the context-size nudge (plan
token-efficiency-2026-09, L1/L4).

The question: after the nudge went live, did the share of cost spent in
`200k+` context calls fall? Share is measured over rows that have cache data
only; `no-cache-data` rows are unknown history, never a small context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from agent_ledger.report.spend import per_context_band

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

Verdict = Literal["PASS", "NO-IMPROVEMENT", "INSUFFICIENT"]


@dataclass(frozen=True)
class ContextCheck:
    """Outcome of comparing the pre- and post-split `200k+` cost share."""

    baseline_share_pct: float
    post_share_pct: float
    post_calls: int
    verdict: Verdict

    def summary(self) -> str:
        """Return a one-line human summary."""
        return (
            f"context-check {self.verdict}: 200k+ share of cost "
            f"{self.baseline_share_pct:.1f}% -> {self.post_share_pct:.1f}% "
            f"({self.post_calls} post-split calls)"
        )


def _share_200k(frame_cost: dict[str, float]) -> float:
    known = sum(v for band, v in frame_cost.items() if band != "no-cache-data")
    return frame_cost.get("200k+", 0.0) / known * 100.0 if known > 0 else 0.0


def context_check(
    db_path: Path,
    split: datetime,
    min_calls: int = 500,
    min_drop_pts: float = 5.0,
) -> ContextCheck:
    """Compare the `200k+` cost share before and after `split`.

    Args:
        db_path: SQLite ledger database path.
        split: Timezone-aware instant the nudge went live.
        min_calls: Post-split calls required before a verdict is meaningful.
        min_drop_pts: Percentage-point drop required for PASS.

    Returns:
        A `ContextCheck`. `INSUFFICIENT` below `min_calls`; `PASS` when the
        share fell by at least `min_drop_pts`; otherwise `NO-IMPROVEMENT`
        (a flag for the owner, not a kill signal).

    Example:
        >>> context_check(db, split).verdict  # doctest: +SKIP
        'INSUFFICIENT'
    """
    pre = per_context_band(db_path, until=split)
    post = per_context_band(db_path, since=split)
    baseline = _share_200k(dict(zip(pre["band"], pre["cost_usd"], strict=True)))
    after = _share_200k(dict(zip(post["band"], post["cost_usd"], strict=True)))
    post_calls = int(post["calls"].sum())
    verdict: Verdict
    if post_calls < min_calls:
        verdict = "INSUFFICIENT"
    elif baseline - after >= min_drop_pts:
        verdict = "PASS"
    else:
        verdict = "NO-IMPROVEMENT"
    return ContextCheck(baseline, after, post_calls, verdict)
