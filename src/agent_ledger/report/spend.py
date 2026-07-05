"""Polars aggregations over stored CallRecords. Output is UI-agnostic plain
dataclasses/frames — no formatting decisions belong in this module."""

from __future__ import annotations

from pathlib import Path

import polars as pl


def per_project(db_path: Path) -> pl.DataFrame:
    """Return one row per project: total in/out tokens, cost, call count,
    and attribution_pct (share of records with a non-empty project).

    M0 acceptance criterion: attribution_pct must be >= 0.8 on real data
    (docs/architecture.md M0 kill criterion) or M0 is not done.

    M0 TODO: read all_records(db_path), group by project, aggregate.
    """

    raise NotImplementedError("M0: implement per_project()")
