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
