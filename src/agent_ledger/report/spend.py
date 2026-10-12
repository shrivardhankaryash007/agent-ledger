"""Polars aggregations over stored CallRecords. Output is UI-agnostic plain
dataclasses/frames — no formatting decisions belong in this module."""

from __future__ import annotations

from datetime import datetime
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


CONTEXT_BANDS: tuple[str, ...] = (
    "no-cache-data",
    "<50k",
    "50-100k",
    "100-200k",
    "200k+",
)


def _context_band(cache_read_tokens: int, calls: int) -> str:
    """Return the band for one row's mean cached context per call."""

    if cache_read_tokens <= 0:
        return "no-cache-data"
    mean = cache_read_tokens / max(calls, 1)
    if mean < 50_000:
        return "<50k"
    if mean < 100_000:
        return "50-100k"
    if mean < 200_000:
        return "100-200k"
    return "200k+"


def per_context_band(
    db_path: Path, since: datetime | None = None, until: datetime | None = None
) -> pl.DataFrame:
    """Return rows, calls, cost and cost share grouped by mean cached context.

    Mean cached context per call is the best available predictor of cost
    (every turn re-sends it). Rows with no cached tokens are reported in a
    separate `no-cache-data` band — unavailable telemetry is never a small
    context.

    Args:
        db_path: SQLite ledger database path.
        since: Keep only rows with `ts >= since` (timezone-aware), if given.
        until: Keep only rows with `ts < until` (timezone-aware), if given.

    Returns:
        A frame with one row per band in `CONTEXT_BANDS` order, columns
        `band`, `rows`, `calls`, `cost_usd`, `cost_share_pct`.
    """
    records = [
        r
        for r in all_records(db_path)
        if (since is None or r.ts >= since) and (until is None or r.ts < until)
    ]
    bands = [_context_band(r.cache_read_tokens, r.calls) for r in records]
    frame = pl.DataFrame(
        {
            "band": bands,
            "calls": [r.calls for r in records],
            "cost_usd": [r.cost_usd for r in records],
        },
        schema={"band": pl.String, "calls": pl.Int64, "cost_usd": pl.Float64},
    )
    grouped = frame.group_by("band").agg(
        pl.len().alias("rows"),
        pl.col("calls").sum(),
        pl.col("cost_usd").sum(),
    )
    full = (
        pl.DataFrame({"band": list(CONTEXT_BANDS)})
        .join(grouped, on="band", how="left")
        .with_columns(
            pl.col("rows").fill_null(0).cast(pl.Int64),
            pl.col("calls").fill_null(0).cast(pl.Int64),
            pl.col("cost_usd").fill_null(0.0),
        )
    )
    total = float(full["cost_usd"].sum())
    share = pl.col("cost_usd") / total * 100.0 if total > 0 else pl.lit(0.0)
    return full.with_columns(share.alias("cost_share_pct")).select(
        "band", "rows", "calls", "cost_usd", "cost_share_pct"
    )
