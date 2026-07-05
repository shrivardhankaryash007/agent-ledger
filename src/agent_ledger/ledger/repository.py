"""SQLite repository for CallRecord. No other module may write to the DB
except through this file (AGENTS.md rule 1)."""

from __future__ import annotations

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
    """Create the schema at db_path if it does not already exist.

    M0 TODO: run SCHEMA_SQL, record SCHEMA_VERSION in schema_meta.
    """

    raise NotImplementedError("M0: implement migrate()")


def upsert(db_path: Path, record: CallRecord) -> None:
    """Insert or update one CallRecord, keyed on (session_id, model_sku).

    M0 TODO: idempotent upsert so re-running ingest is safe.
    """

    raise NotImplementedError("M0: implement upsert()")


def all_records(db_path: Path) -> list[CallRecord]:
    """Return every CallRecord currently stored.

    M0 TODO: read call_records, hydrate CallRecord instances.
    """

    raise NotImplementedError("M0: implement all_records()")
