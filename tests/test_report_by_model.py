"""Packet AL-B acceptance: `agent-ledger report --by model` (written to fail first)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from agent_ledger.cli import app
from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.repository import migrate, upsert
from agent_ledger.report.spend import per_model

runner = CliRunner()
COLUMNS = [
    "model_sku",
    "vendor",
    "in_tokens",
    "out_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_usd",
    "calls",
]


def _record(
    session: str, model: str, vendor: str, cost: float, **tokens: int
) -> CallRecord:
    return CallRecord(
        ts=datetime(2026, 10, 1, tzinfo=UTC),
        session_id=session,
        project="proj",
        model_sku=model,
        capability_class="general_strong",
        vendor=vendor,
        in_tokens=tokens.get("in_tokens", 10),
        out_tokens=tokens.get("out_tokens", 5),
        cache_read_tokens=tokens.get("cache_read_tokens", 0),
        cache_write_tokens=tokens.get("cache_write_tokens", 0),
        cost_usd=cost,
        calls=tokens.get("calls", 1),
    )


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "ledger.db"
    migrate(db)
    upsert(
        db,
        _record(
            "s1", "model-a", "anthropic", 1.0, in_tokens=100, out_tokens=10, calls=2
        ),
    )
    upsert(
        db,
        _record("s2", "model-a", "anthropic", 2.0, in_tokens=200, cache_read_tokens=50),
    )
    upsert(db, _record("s3", "model-b", "anthropic", 9.0, cache_write_tokens=7))
    upsert(db, _record("s4", "model-c", "openai", 0.5))
    upsert(db, _record("s5", "model-c", "other", 0.5))
    return db


def test_per_model_groups_sums_and_orders_by_cost_then_name(tmp_path: Path) -> None:
    frame = per_model(_db(tmp_path))

    assert frame.columns == COLUMNS
    assert frame["model_sku"].to_list() == ["model-b", "model-a", "model-c", "model-c"]
    a = frame.filter(pl.col("model_sku") == "model-a").row(0, named=True)
    assert a["in_tokens"] == 300 and a["out_tokens"] == 15 and a["calls"] == 3
    assert a["cache_read_tokens"] == 50
    assert a["cost_usd"] == 3.0
    # The same model under two vendors stays two rows;
    # ties on cost sort by model, then vendor.
    assert frame.filter(pl.col("model_sku") == "model-c")["vendor"].to_list() == [
        "openai",
        "other",
    ]


def test_per_model_on_an_empty_ledger_has_the_columns_and_no_rows(
    tmp_path: Path,
) -> None:
    db = tmp_path / "empty.db"
    migrate(db)
    frame = per_model(db)
    assert frame.columns == COLUMNS and frame.height == 0


def test_cli_report_by_model_prints_models_not_projects(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["report", "--by", "model", "--db-path", str(_db(tmp_path))]
    )
    assert result.exit_code == 0
    assert "model-a" in result.output and "model_sku" in result.output
    assert "proj" not in result.output


def test_cli_report_default_is_still_by_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["report", "--db-path", str(_db(tmp_path))])
    assert result.exit_code == 0
    assert "proj" in result.output and "model_sku" not in result.output


def test_cli_report_rejects_an_unknown_grouping(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["report", "--by", "nonsense", "--db-path", str(_db(tmp_path))]
    )
    assert result.exit_code == 2
    assert "--by" in result.output
