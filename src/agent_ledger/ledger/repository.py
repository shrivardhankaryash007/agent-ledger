"""SQLite repository for CallRecord. No other module may write to the DB
except through this file (AGENTS.md rule 1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agent_ledger.ledger.models import CallRecord

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);

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
    cost_usd REAL NOT NULL,
    calls INTEGER NOT NULL,
    PRIMARY KEY (session_id, model_sku)
);
"""


def migrate(db_path: Path) -> None:
    """Create the schema at ``db_path`` and record its version."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_SQL)
        row = connection.execute("SELECT version FROM schema_meta").fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO schema_meta (version) VALUES (?)", (SCHEMA_VERSION,)
            )
        elif row[0] != SCHEMA_VERSION:
            msg = f"unsupported schema version {row[0]}; expected {SCHEMA_VERSION}"
            raise RuntimeError(msg)


def upsert(db_path: Path, record: CallRecord) -> None:
    """Insert or update one record, keyed on ``(session_id, model_sku)``."""

    migrate(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO call_records (
                model_version, ts, session_id, project, model_sku,
                capability_class, vendor, in_tokens, out_tokens, cost_usd, calls
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id, model_sku) DO UPDATE SET
                model_version = excluded.model_version,
                ts = excluded.ts,
                project = excluded.project,
                capability_class = excluded.capability_class,
                vendor = excluded.vendor,
                in_tokens = excluded.in_tokens,
                out_tokens = excluded.out_tokens,
                cost_usd = excluded.cost_usd,
                calls = excluded.calls
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
                record.cost_usd,
                record.calls,
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
                   capability_class, vendor, in_tokens, out_tokens, cost_usd, calls
            FROM call_records
            ORDER BY session_id, model_sku
            """
        ).fetchall()
    return [CallRecord.model_validate(dict(row)) for row in rows]
