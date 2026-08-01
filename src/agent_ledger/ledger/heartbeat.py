"""Collector heartbeat and staleness reporting.

Fix 2 (2026-08-02, agent-ledger fix spec v2): ingestion had no scheduler and
no failure signal, so a 26-day silent gap (2026-07-06 -> 2026-08-01) was
indistinguishable from "nothing happened because there was nothing to
ingest." ``record_success``/``record_failure`` write one row per `ingest`
invocation; ``build_report`` is what `agent-ledger doctor` prints.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_ledger.ledger.repository import migrate

STALE_THRESHOLD_HOURS = 72.0

_STATUS_SUCCESS = "success"
_STATUS_FAILURE = "failure"


def record_success(db_path: Path, rows_written: int) -> None:
    """Record one successful collector run."""

    _record(db_path, status=_STATUS_SUCCESS, error=None, rows_written=rows_written)


def record_failure(db_path: Path, error: str) -> None:
    """Record one failed collector run, preserving the error for `doctor`."""

    _record(db_path, status=_STATUS_FAILURE, error=error, rows_written=0)


def _record(
    db_path: Path, *, status: str, error: str | None, rows_written: int
) -> None:
    migrate(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO collector_heartbeat (ts, status, error, rows_written)
            VALUES (?, ?, ?, ?)
            """,
            (datetime.now(UTC).isoformat(), status, error, rows_written),
        )


@dataclass(frozen=True)
class DoctorReport:
    """Snapshot printed by ``agent-ledger doctor``."""

    newest_row_ts: datetime | None
    newest_row_age_hours: float | None
    last_heartbeat_ts: datetime | None
    last_heartbeat_status: str | None
    last_heartbeat_error: str | None
    rows_last_7_days: int
    total_rows: int
    is_stale: bool


def build_report(db_path: Path, *, now: datetime | None = None) -> DoctorReport:
    """Compute the current staleness snapshot.

    Args:
        db_path: Ledger database path.
        now: Injectable clock for tests; defaults to the real current time.

    Returns:
        A ``DoctorReport``. ``is_stale`` is true whenever there is no logged
        row at all, or the newest one is older than ``STALE_THRESHOLD_HOURS``.
    """

    migrate(db_path)
    current = now or datetime.now(UTC)
    with sqlite3.connect(db_path) as connection:
        newest_row_raw = connection.execute(
            "SELECT MAX(ts) FROM call_records"
        ).fetchone()[0]
        total_rows = connection.execute("SELECT COUNT(*) FROM call_records").fetchone()[
            0
        ]
        heartbeat_row = connection.execute(
            "SELECT ts, status, error FROM collector_heartbeat ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        week_ago = (current - timedelta(days=7)).isoformat()
        rows_last_7_days = connection.execute(
            "SELECT COUNT(*) FROM call_records WHERE ts >= ?", (week_ago,)
        ).fetchone()[0]

    newest_row_ts = datetime.fromisoformat(newest_row_raw) if newest_row_raw else None
    age_hours = (
        (current - newest_row_ts).total_seconds() / 3600.0
        if newest_row_ts is not None
        else None
    )
    last_heartbeat_ts = (
        datetime.fromisoformat(heartbeat_row[0]) if heartbeat_row else None
    )
    last_heartbeat_status = heartbeat_row[1] if heartbeat_row else None
    last_heartbeat_error = heartbeat_row[2] if heartbeat_row else None

    return DoctorReport(
        newest_row_ts=newest_row_ts,
        newest_row_age_hours=age_hours,
        last_heartbeat_ts=last_heartbeat_ts,
        last_heartbeat_status=last_heartbeat_status,
        last_heartbeat_error=last_heartbeat_error,
        rows_last_7_days=rows_last_7_days,
        total_rows=total_rows,
        is_stale=age_hours is None or age_hours > STALE_THRESHOLD_HOURS,
    )
