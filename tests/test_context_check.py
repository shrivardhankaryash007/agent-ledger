"""Packet TE-L4b acceptance: pre-registered success check for the context nudge.

Verdict is pre-registered: PASS when the `200k+` share of cache-data cost
drops by at least `min_drop_pts` after the split date with enough calls;
INSUFFICIENT when the post window has too few calls; otherwise NO-IMPROVEMENT
(a flag, never a kill).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from agent_ledger.cli import app
from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.repository import migrate, upsert
from agent_ledger.report.context_check import context_check
from agent_ledger.report.spend import per_context_band

runner = CliRunner()
SPLIT = datetime(2026, 10, 12, tzinfo=UTC)


def _rec(session: str, day: int, cost: float, calls: int, mean_ctx: int) -> CallRecord:
    return CallRecord(
        ts=datetime(2026, 10, day, tzinfo=UTC),
        session_id=session,
        project="p",
        model_sku="m",
        capability_class="general_strong",
        vendor="anthropic",
        in_tokens=1,
        out_tokens=1,
        cache_read_tokens=mean_ctx * calls,
        cache_write_tokens=0,
        cost_usd=cost,
        calls=calls,
    )


def _db(tmp_path: Path, post_big_cost: float, post_calls: int) -> Path:
    db = tmp_path / "l.db"
    migrate(db)
    upsert(db, _rec("pre-big", 1, 6.0, 1000, 250_000))
    upsert(db, _rec("pre-small", 2, 4.0, 1000, 60_000))
    upsert(db, _rec("post-big", 13, post_big_cost, post_calls, 250_000))
    upsert(db, _rec("post-small", 14, 10.0 - post_big_cost, post_calls, 60_000))
    return db


def test_window_filters_split_the_bands(tmp_path: Path) -> None:
    db = _db(tmp_path, 1.0, 1000)
    pre = per_context_band(db, until=SPLIT)
    post = per_context_band(db, since=SPLIT)
    assert sum(pre["cost_usd"]) == 10.0
    assert sum(post["cost_usd"]) == 10.0
    assert dict(zip(post["band"], post["cost_usd"], strict=True))["200k+"] == 1.0


def test_pass_when_share_drops_enough(tmp_path: Path) -> None:
    result = context_check(_db(tmp_path, 2.0, 1000), SPLIT)
    assert result.baseline_share_pct == 60.0
    assert result.post_share_pct == 20.0
    assert result.verdict == "PASS"


def test_no_improvement_when_share_holds(tmp_path: Path) -> None:
    assert context_check(_db(tmp_path, 6.0, 1000), SPLIT).verdict == "NO-IMPROVEMENT"


def test_insufficient_when_few_post_calls(tmp_path: Path) -> None:
    result = context_check(_db(tmp_path, 1.0, 10), SPLIT, min_calls=500)
    assert result.verdict == "INSUFFICIENT"


def test_cli_context_check_prints_verdict_and_exits_zero(tmp_path: Path) -> None:
    db = _db(tmp_path, 2.0, 1000)
    result = runner.invoke(
        app, ["context-check", "--db-path", str(db), "--split", "2026-10-12"]
    )
    assert result.exit_code == 0
    assert "PASS" in result.output
