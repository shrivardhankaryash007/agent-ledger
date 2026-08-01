"""Fix 2 (2026-08-02): heartbeat + staleness doctor report."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_ledger.ledger.heartbeat import (
    STALE_THRESHOLD_HOURS,
    build_report,
    record_failure,
    record_success,
)
from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.repository import upsert


def _record(ts: datetime, session_id: str) -> CallRecord:
    return CallRecord(
        ts=ts,
        session_id=session_id,
        project="dev",
        model_sku="claude-sonnet-4-6",
        capability_class="coding_strong",
        vendor="anthropic",
        in_tokens=100,
        out_tokens=20,
        cost_usd=0.001,
        calls=1,
    )


def test_report_on_empty_ledger_is_stale_with_no_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"

    report = build_report(db_path)

    assert report.total_rows == 0
    assert report.newest_row_ts is None
    assert report.last_heartbeat_ts is None
    assert report.is_stale is True


def test_report_is_fresh_just_after_a_successful_ingest(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    upsert(db_path, _record(now, "sess-1"))
    record_success(db_path, rows_written=1)

    report = build_report(db_path, now=now)

    assert report.total_rows == 1
    assert report.newest_row_age_hours == 0.0
    assert report.last_heartbeat_status == "success"
    assert report.is_stale is False


def test_report_is_stale_past_the_threshold(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    old = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    upsert(db_path, _record(old, "sess-old"))
    now = old + timedelta(hours=STALE_THRESHOLD_HOURS + 1)

    report = build_report(db_path, now=now)

    assert report.newest_row_age_hours == STALE_THRESHOLD_HOURS + 1
    assert report.is_stale is True


def test_failure_heartbeat_carries_its_error(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    record_failure(db_path, "no pricing configured for transcript model 'x'")

    report = build_report(db_path)

    assert report.last_heartbeat_status == "failure"
    assert (
        report.last_heartbeat_error == "no pricing configured for transcript model 'x'"
    )
    # A failed run wrote no call_records, so this is still stale.
    assert report.is_stale is True


def test_rows_last_7_days_excludes_older_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    upsert(db_path, _record(now - timedelta(days=1), "sess-recent"))
    upsert(db_path, _record(now - timedelta(days=10), "sess-old"))

    report = build_report(db_path, now=now)

    assert report.rows_last_7_days == 1
    assert report.total_rows == 2
