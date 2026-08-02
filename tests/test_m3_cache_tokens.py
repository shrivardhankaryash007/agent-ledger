"""M3 acceptance: cache tokens are captured, priced, and migrated.

Written to fail before the v3 implementation exists (AGENTS.md rule 5).

The defect these tests pin down: `ingest.claude_transcripts.parse_transcript`
summed `input_tokens` + `cache_creation_input_tokens` into `in_tokens` and
never read `cache_read_input_tokens` at all. On a harness that re-sends a
large cached prefix on every call, cache reads are the dominant token volume
— so both the token totals and `cost_usd` were understated by an unbounded
margin, and the share of spend attributable to always-loaded context was not
computable from the ledger at all.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_ledger.ingest.claude_transcripts import parse_transcript
from agent_ledger.ledger.models import MODEL_VERSION, CallRecord
from agent_ledger.ledger.pricing import Price, cost_usd
from agent_ledger.ledger.repository import (
    SCHEMA_VERSION,
    all_records,
    migrate,
    upsert,
)

PRICED_MODEL = "claude-sonnet-5"


def _write_transcript(path: Path, usages: list[dict[str, int]]) -> None:
    """Write a minimal JSONL transcript containing one assistant line per usage."""

    lines = [
        json.dumps(
            {
                "sessionId": "sess-m3",
                "cwd": str(path.parent),
                "timestamp": f"2026-08-02T10:0{index}:00Z",
                "message": {"model": PRICED_MODEL, "usage": usage},
            }
        )
        for index, usage in enumerate(usages)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_transcript_captures_cache_read_tokens(tmp_path: Path) -> None:
    """`cache_read_input_tokens` must land in its own field, not be dropped."""

    transcript = tmp_path / "sess-m3.jsonl"
    _write_transcript(
        transcript,
        [
            {
                "input_tokens": 100,
                "cache_creation_input_tokens": 19_000,
                "cache_read_input_tokens": 0,
                "output_tokens": 500,
            },
            {
                "input_tokens": 200,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 19_000,
                "output_tokens": 700,
            },
        ],
    )

    (record,) = parse_transcript(transcript)

    assert record.cache_read_tokens == 19_000
    assert record.cache_write_tokens == 19_000
    # in_tokens keeps its v1/v2 meaning (fresh input + cache writes) so every
    # historical row stays comparable; cache_write_tokens is an additive
    # breakdown of it, deliberately redundant. Do not "clean this up".
    assert record.in_tokens == 19_300
    assert record.out_tokens == 1_200


def test_parse_transcript_defaults_cache_fields_to_zero(tmp_path: Path) -> None:
    """A transcript with no cache keys must yield zeros, never None."""

    transcript = tmp_path / "sess-nocache.jsonl"
    _write_transcript(transcript, [{"input_tokens": 50, "output_tokens": 10}])

    (record,) = parse_transcript(transcript)

    assert record.cache_read_tokens == 0
    assert record.cache_write_tokens == 0
    assert record.in_tokens == 50


def test_cost_usd_prices_cache_reads_below_fresh_input() -> None:
    """Cache reads must be billed, and billed cheaper than fresh input."""

    prices = {
        PRICED_MODEL: Price(
            input_rate=3.0 / 1000,
            output_rate=15.0 / 1000,
            cache_read_rate=0.3 / 1000,
            cache_write_rate=3.75 / 1000,
        )
    }

    without_cache = cost_usd(PRICED_MODEL, 1_000, 0, prices)
    with_cache = cost_usd(PRICED_MODEL, 1_000, 0, prices, cache_read_tokens=1_000)

    assert with_cache > without_cache, "cache reads must not be free"
    assert with_cache < without_cache * 2, "cache reads must be cheaper than input"


def test_cost_usd_does_not_double_charge_cache_writes() -> None:
    """`in_tokens` already contains cache writes; they must be re-rated, not added."""

    prices = {
        PRICED_MODEL: Price(
            input_rate=3.0 / 1000,
            output_rate=15.0 / 1000,
            cache_read_rate=0.3 / 1000,
            cache_write_rate=3.75 / 1000,
        )
    }

    # All 1000 in_tokens are cache writes, so none are charged at input_rate.
    # Rates are per-1000-tokens: 1000/1000 * (3.75/1000).
    cost = cost_usd(PRICED_MODEL, 1_000, 0, prices, cache_write_tokens=1_000)

    assert cost == pytest.approx(1_000 / 1000 * (3.75 / 1000))
    # Sanity: strictly cheaper than charging the same tokens twice.
    assert cost < cost_usd(PRICED_MODEL, 1_000, 0, prices) + 1_000 / 1000 * (
        3.75 / 1000
    )


def test_migrate_v2_database_to_v3_preserves_rows(tmp_path: Path) -> None:
    """A live v2 DB must gain the cache columns without losing a single row."""

    db_path = tmp_path / "ledger.db"
    migrate(db_path)
    # Force the DB back to the v2 shape a real deployed database is in.
    with sqlite3.connect(db_path) as connection:
        for column in ("cache_read_tokens", "cache_write_tokens"):
            connection.execute(f"ALTER TABLE call_records DROP COLUMN {column}")
        connection.execute("UPDATE schema_meta SET version = 2")
        connection.execute(
            """
            INSERT INTO call_records (
                model_version, ts, session_id, project, model_sku,
                capability_class, vendor, in_tokens, out_tokens, cost_usd, calls
            ) VALUES (2, '2026-07-01T00:00:00+00:00', 'legacy', 'dev',
                      ?, 'coding_strong', 'anthropic', 999, 111, 1.5, 7)
            """,
            (PRICED_MODEL,),
        )

    migrate(db_path)

    with sqlite3.connect(db_path) as connection:
        version = connection.execute("SELECT version FROM schema_meta").fetchone()[0]
    assert version == SCHEMA_VERSION

    (legacy,) = [r for r in all_records(db_path) if r.session_id == "legacy"]
    assert legacy.in_tokens == 999, "historical spend must survive migration"
    # Legacy rows predate cache capture: zero means "not measured", and the
    # re-ingest pass is what repopulates them where the transcript survives.
    assert legacy.cache_read_tokens == 0
    assert legacy.cache_write_tokens == 0


def test_upsert_roundtrips_cache_fields(tmp_path: Path) -> None:
    """Cache fields must survive a write/read cycle through the repository."""

    db_path = tmp_path / "ledger.db"
    record = CallRecord(
        ts=datetime(2026, 8, 2, tzinfo=UTC),
        session_id="roundtrip",
        project="dev",
        model_sku=PRICED_MODEL,
        capability_class="coding_strong",
        vendor="anthropic",
        in_tokens=1_000,
        out_tokens=200,
        cache_read_tokens=1_400_000,
        cache_write_tokens=19_000,
        cost_usd=4.2,
        calls=76,
    )
    upsert(db_path, record)

    (stored,) = all_records(db_path)
    assert stored.model_version == MODEL_VERSION
    assert stored.cache_read_tokens == 1_400_000
    assert stored.cache_write_tokens == 19_000
