"""Polars aggregations over stored CallRecords. Output is UI-agnostic plain
dataclasses/frames — no formatting decisions belong in this module."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from agent_ledger.ledger.repository import all_records


def per_project(db_path: Path) -> pl.DataFrame:
    """Return summed token, cost, and call totals grouped by project."""

    records = all_records(db_path)
    frame = pl.DataFrame(
        {
            "project": [record.project for record in records],
            "in_tokens": [record.in_tokens for record in records],
            "out_tokens": [record.out_tokens for record in records],
            "cost_usd": [record.cost_usd for record in records],
            "calls": [record.calls for record in records],
        },
        schema={
            "project": pl.String,
            "in_tokens": pl.Int64,
            "out_tokens": pl.Int64,
            "cost_usd": pl.Float64,
            "calls": pl.Int64,
        },
    )
    return (
        frame.group_by("project")
        .agg(
            pl.col("in_tokens").sum(),
            pl.col("out_tokens").sum(),
            pl.col("cost_usd").sum(),
            pl.col("calls").sum(),
        )
        .sort("project")
    )


def per_model(db_path: Path) -> pl.DataFrame:
    """Return summed token, cost, and call totals grouped by model and vendor.

    Args:
        db_path: SQLite ledger database path.

    Returns:
        A frame with one sorted row per model and vendor pair.
    """
    records = all_records(db_path)
    frame = pl.DataFrame(
        {
            "model_sku": [record.model_sku for record in records],
            "vendor": [record.vendor for record in records],
            "in_tokens": [record.in_tokens for record in records],
            "out_tokens": [record.out_tokens for record in records],
            "cache_read_tokens": [record.cache_read_tokens for record in records],
            "cache_write_tokens": [record.cache_write_tokens for record in records],
            "cost_usd": [record.cost_usd for record in records],
            "calls": [record.calls for record in records],
        },
        schema={
            "model_sku": pl.String,
            "vendor": pl.String,
            "in_tokens": pl.Int64,
            "out_tokens": pl.Int64,
            "cache_read_tokens": pl.Int64,
            "cache_write_tokens": pl.Int64,
            "cost_usd": pl.Float64,
            "calls": pl.Int64,
        },
    )
    return (
        frame.group_by("model_sku", "vendor")
        .agg(
            pl.col("in_tokens").sum(),
            pl.col("out_tokens").sum(),
            pl.col("cache_read_tokens").sum(),
            pl.col("cache_write_tokens").sum(),
            pl.col("cost_usd").sum(),
            pl.col("calls").sum(),
        )
        .sort(
            ["cost_usd", "model_sku", "vendor"],
            descending=[True, False, False],
        )
    )
