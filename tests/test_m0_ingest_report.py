"""M0 acceptance test (docs/architecture.md).

'Real historical spend from existing Claude Code transcripts renders as a
per-project table.' Fixtures mimic ~/.claude/projects/<project-dir>/*.jsonl:
one project directory per project, which is exactly the fact
ingest.claude_transcripts must capture and today's workspace ledger discards.

FAILS now because ingest() and per_project() raise NotImplementedError.
Passes only once:
  1. ingest() walks the fixture tree and upserts one CallRecord per
     (session, model), with `project` set from the parent directory name.
  2. per_project() aggregates those records correctly, including an
     attribution_pct field computed as (records with non-empty project) /
     (total records).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_ledger.ingest.claude_transcripts import ingest
from agent_ledger.report.spend import per_project

FIXTURES = Path(__file__).parent / "fixtures" / "claude_projects"

PROJECT_DEV = "-Users-yashshrivardhankar-dev"
PROJECT_CARELEDGER = "-Users-yashshrivardhankar-careledger"


def test_ingest_and_per_project_report(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"

    written = ingest(FIXTURES, db_path)
    assert written == 2  # one CallRecord per (session, model): sess-a1, sess-b1

    frame = per_project(db_path)
    rows = {row["project"]: row for row in frame.to_dicts()}

    assert set(rows) == {PROJECT_DEV, PROJECT_CARELEDGER}

    dev_row = rows[PROJECT_DEV]
    assert dev_row["in_tokens"] == 1500  # 1000 + 500, both lines same session+model
    assert dev_row["out_tokens"] == 300  # 200 + 100
    assert dev_row["cost_usd"] == pytest.approx(0.009, rel=1e-6)

    careledger_row = rows[PROJECT_CARELEDGER]
    assert careledger_row["in_tokens"] == 2000
    assert careledger_row["out_tokens"] == 300
    assert careledger_row["cost_usd"] == pytest.approx(0.0035, rel=1e-6)

    # M0 kill criterion (docs/architecture.md): >= 80% of records attributed
    # to a real project. Both fixture projects are attributed, so this must
    # be 1.0 once implemented — a value below 0.8 here on real data is the
    # signal to stop and rescope attribution instead of continuing to M1.
    total_calls = sum(row["calls"] for row in rows.values())
    attributed_calls = sum(
        row["calls"] for row in rows.values() if row["project"] not in ("", "unknown")
    )
    assert attributed_calls / total_calls >= 0.8
