"""SQLite repository for CallRecord. No other module may write to the DB
except through this file (AGENTS.md rule 1)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from agent_ledger.ledger.models import CallRecord

SCHEMA_VERSION = 3

SCHEMA_META_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
"""

# Includes the v2 attribution columns (repo_name, worktree_name, branch,
# cwd_raw, label_source) so a brand-new database is created at the current
# shape directly. An existing v1 database instead goes through the
# ALTER TABLE path in migrate() below — CREATE TABLE IF NOT EXISTS is a
# no-op against an already-existing table, columns and all.
CALL_RECORDS_SQL = """
CREATE TABLE IF NOT EXISTS call_records (
    model_version INTEGER NOT NULL,
    ts TEXT NOT NULL,
    session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    model_sku TEXT NOT NULL,
    capability_class TEXT NOT NULL,
    vendor TEXT NOT NULL,
    in_tokens INTEGER NOT NULL,
    out_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL,
    calls INTEGER NOT NULL,
    repo_name TEXT,
    worktree_name TEXT,
    branch TEXT,
    cwd_raw TEXT,
    label_source TEXT,
    PRIMARY KEY (session_id, model_sku)
);
"""

# Fix 2 (2026-08-02): one row per `ingest` invocation, success or failure,
# so a silent 26-day collection gap becomes a measurable staleness signal
# instead of nothing at all. See agent_ledger.ledger.heartbeat.
HEARTBEAT_SQL = """
CREATE TABLE IF NOT EXISTS collector_heartbeat (
    ts TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    rows_written INTEGER NOT NULL
);
"""

_V1_TO_V2_COLUMNS = ("repo_name", "worktree_name", "branch", "cwd_raw", "label_source")
# v3 (2026-08-02): cache accounting. NOT NULL DEFAULT 0 rather than nullable —
# a pre-v3 row genuinely has zero *measured* cache volume, and the re-ingest
# pass is what replaces the zero with the real figure wherever the source
# transcript still exists on disk.
_V2_TO_V3_COLUMNS = ("cache_read_tokens", "cache_write_tokens")


def migrate(db_path: Path) -> None:
    """Create or upgrade the schema at ``db_path`` in place, no data loss.

    Upgrades are cumulative: a v1 database gains the v2 attribution columns
    and then the v3 cache columns in the same call, so a database that sat
    out a release still lands on the current shape in one step.
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_META_SQL + CALL_RECORDS_SQL + HEARTBEAT_SQL)
        row = connection.execute("SELECT version FROM schema_meta").fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO schema_meta (version) VALUES (?)", (SCHEMA_VERSION,)
            )
            return
        current_version = row[0]
        if current_version == SCHEMA_VERSION:
            return
        if current_version not in (1, 2):
            msg = (
                f"unsupported schema version {current_version}; "
                f"expected {SCHEMA_VERSION}"
            )
            raise RuntimeError(msg)

        existing_columns = {
            info[1] for info in connection.execute("PRAGMA table_info(call_records)")
        }
        # Every column name below is a fixed literal from the tuples above,
        # never external input.
        if current_version == 1:
            for column in _V1_TO_V2_COLUMNS:
                if column not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE call_records ADD COLUMN {column} TEXT"
                    )
        for column in _V2_TO_V3_COLUMNS:
            if column not in existing_columns:
                connection.execute(
                    f"ALTER TABLE call_records "
                    f"ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
                )
        connection.execute("UPDATE schema_meta SET version = ?", (SCHEMA_VERSION,))


def upsert(db_path: Path, record: CallRecord) -> None:
    """Insert or update one record, keyed on ``(session_id, model_sku)``."""

    migrate(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO call_records (
                model_version, ts, session_id, project, model_sku,
                capability_class, vendor, in_tokens, out_tokens,
                cache_read_tokens, cache_write_tokens, cost_usd,
                calls, repo_name, worktree_name, branch, cwd_raw, label_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id, model_sku) DO UPDATE SET
                model_version = excluded.model_version,
                ts = excluded.ts,
                project = excluded.project,
                capability_class = excluded.capability_class,
                vendor = excluded.vendor,
                in_tokens = excluded.in_tokens,
                out_tokens = excluded.out_tokens,
                cache_read_tokens = excluded.cache_read_tokens,
                cache_write_tokens = excluded.cache_write_tokens,
                cost_usd = excluded.cost_usd,
                calls = excluded.calls,
                repo_name = excluded.repo_name,
                worktree_name = excluded.worktree_name,
                branch = excluded.branch,
                cwd_raw = excluded.cwd_raw,
                label_source = excluded.label_source
            """,
            (
                record.model_version,
                record.ts.isoformat(),
                record.session_id,
                record.project,
                record.model_sku,
                record.capability_class,
                record.vendor,
                record.in_tokens,
                record.out_tokens,
                record.cache_read_tokens,
                record.cache_write_tokens,
                record.cost_usd,
                record.calls,
                record.repo_name,
                record.worktree_name,
                record.branch,
                record.cwd_raw,
                record.label_source,
            ),
        )


def all_records(db_path: Path) -> list[CallRecord]:
    """Return every stored record in deterministic key order."""

    migrate(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT model_version, ts, session_id, project, model_sku,
                   capability_class, vendor, in_tokens, out_tokens,
                   cache_read_tokens, cache_write_tokens, cost_usd,
                   calls, repo_name, worktree_name, branch, cwd_raw,
                   label_source
            FROM call_records
            ORDER BY session_id, model_sku
            """
        ).fetchall()
    return [CallRecord.model_validate(dict(row)) for row in rows]


def update_labels(
    db_path: Path,
    *,
    session_id: str,
    model_sku: str,
    project: str,
    repo_name: str | None,
    worktree_name: str | None,
    branch: str | None,
    label_source: str | None,
) -> None:
    """Backfill attribution columns on one already-stored row in place.

    Used only by the one-off 2026-08 backfill (scripts/backfill_labels.py).
    ``project`` is included and expected to follow the same convention live
    ingest uses (``repo_name`` when resolved, else ``"unknown"``) — leaving
    it at its pre-fix value would keep `report`/`replay` grouping legacy
    rows under the exact broken labels this fix removes. Tokens/cost/
    ``session_id`` are never touched here — that is the original historical
    record and stays exactly as ingested.
    """

    migrate(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE call_records
            SET project = ?, repo_name = ?, worktree_name = ?, branch = ?,
                label_source = ?
            WHERE session_id = ? AND model_sku = ?
            """,
            (
                project,
                repo_name,
                worktree_name,
                branch,
                label_source,
                session_id,
                model_sku,
            ),
        )


def delete_by_session_ids(db_path: Path, session_ids: Iterable[str]) -> int:
    """Delete every row whose exact ``session_id`` is in ``session_ids``.

    Used only by the one-off 2026-08 backfill (scripts/backfill_labels.py)
    to remove pre-migration rows proven redundant: their source transcript
    still exists on disk and has already been fully reprocessed under the
    v2 bucketing scheme, so the old row is a stale duplicate, not unique
    history. Never used for rows whose source no longer exists — those are
    the one irreplaceable copy of that spend and must survive (AGENTS.md
    rule 1).
    """

    migrate(db_path)
    ids = list(session_ids)
    if not ids:
        return 0
    with sqlite3.connect(db_path) as connection:
        # placeholders is just N repeated "?" markers; ids are still bound
        # as parameters below, never interpolated into the SQL text.
        placeholders = ",".join("?" for _ in ids)
        cursor = connection.execute(
            f"DELETE FROM call_records WHERE session_id IN ({placeholders})",
            ids,
        )
        return cursor.rowcount
