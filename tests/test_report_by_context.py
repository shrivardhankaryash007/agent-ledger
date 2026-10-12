"""Packet TE-L4 acceptance: `agent-ledger report --by context` (written to fail first).

Average cached context per call (cache_read_tokens / calls) predicts cost;
rows with no cache data are reported separately, never as a small context.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from agent_ledger.cli import app
from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.repository import migrate, upsert
from agent_ledger.report.spend import CONTEXT_BANDS, per_context_band

runner = CliRunner()


def _record(session: str, cost: float, calls: int, cache_read: int) -> CallRecord:
    return CallRecord(
        ts=datetime(2026, 10, 1, tzinfo=UTC),
        session_id=session,
        project="proj",
        model_sku="model-a",
        capability_class="general_strong",
        vendor="anthropic",
        in_tokens=10,
        out_tokens=5,
        cache_read_tokens=cache_read,
        cache_write_tokens=0,
        cost_usd=cost,
        calls=calls,
    )


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "ledger.db"
    migrate(db)
    upsert(db, _record("none", 1.0, 10, 0))
    upsert(db, _record("small", 2.0, 10, 10 * 49_999))
    upsert(db, _record("mid", 3.0, 10, 10 * 50_000))
    upsert(db, _record("big", 4.0, 10, 10 * 150_000))
    upsert(db, _record("huge", 10.0, 10, 10 * 200_000))
    return db


def test_bands_partition_cost_and_calls(tmp_path: Path) -> None:
    frame = per_context_band(_db(tmp_path))
    rows = {row["band"]: row for row in frame.iter_rows(named=True)}
    assert list(frame["band"]) == list(CONTEXT_BANDS)
    assert rows["no-cache-data"]["cost_usd"] == 1.0
    assert rows["<50k"]["cost_usd"] == 2.0
    assert rows["50-100k"]["cost_usd"] == 3.0
    assert rows["100-200k"]["cost_usd"] == 4.0
    assert rows["200k+"]["cost_usd"] == 10.0
    assert sum(frame["cost_usd"]) == 20.0
    assert sum(frame["calls"]) == 50
    assert abs(sum(frame["cost_share_pct"]) - 100.0) < 1e-6


def test_empty_ledger_returns_all_bands_zeroed(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    migrate(db)
    frame = per_context_band(db)
    assert list(frame["band"]) == list(CONTEXT_BANDS)
    assert sum(frame["cost_usd"]) == 0.0
    assert sum(frame["cost_share_pct"]) == 0.0


def test_cli_report_by_context(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["report", "--db-path", str(_db(tmp_path)), "--by", "context"]
    )
    assert result.exit_code == 0
    assert "200k+" in result.output
    assert "no-cache-data" in result.output
