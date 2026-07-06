"""M0 attribution rescope (agent-ledger/STATUS.md, 2026-07-06 owner decision).

The M0 kill-criterion ("<80% of calls attributable to a project") fired
against the real transcript corpus: 11.6% attribution, because Claude Code
sessions are almost always started from the workspace root (`~/dev`), so
`path.parent.name` (the transcript file's parent directory, set once at
session *start*) is `-Users-yashshrivardhankar-dev` for the overwhelming
majority of calls, even when the session later touches a specific project.

Real transcript inspection (2026-07-06) confirmed each JSONL line carries its
own `cwd` field that *does* track the working directory at the time of that
specific message, and that it changes mid-session (e.g. a root-started
session that later `cd`s into `careledger/`). This fixture reproduces that
exact shape: one session, one transcript file, three lines — the first at
the workspace root, the next two inside `careledger/`.

FAILS now because `parse_transcript` ignores the per-line `cwd` field
entirely and buckets every line in a transcript under one
`project=path.parent.name` value regardless of `cwd`.

Passes only once `parse_transcript` buckets by `(model, cwd)` instead of by
`model` alone, and derives each bucket's `CallRecord.project` from
`Path(cwd).name` when a line carries a `cwd` field — falling back to the
existing `path.parent.name` behavior for lines/files with no `cwd` (keeps
the M0 acceptance test in `test_m0_ingest_report.py` passing unchanged,
since that fixture has no `cwd` field at all).
"""

from __future__ import annotations

from pathlib import Path

from agent_ledger.ingest.claude_transcripts import ingest
from agent_ledger.report.spend import per_project

FIXTURES = Path(__file__).parent / "fixtures" / "claude_projects_cwd"


def test_mixed_cwd_session_splits_by_actual_project(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"

    written = ingest(FIXTURES, db_path)
    # One CallRecord per (session, model, cwd-derived-project): "dev" and
    # "careledger" are different projects even though they share one
    # transcript file and one sessionId.
    assert written == 2

    frame = per_project(db_path)
    rows = {row["project"]: row for row in frame.to_dicts()}

    # The old behavior (`path.parent.name`) would produce exactly one row,
    # "-Users-yashshrivardhankar-dev", with all 3500/700 tokens lumped
    # together. The rescoped behavior must split by the real cwd instead.
    assert set(rows) == {"dev", "careledger"}
    assert "-Users-yashshrivardhankar-dev" not in rows

    dev_row = rows["dev"]
    assert dev_row["in_tokens"] == 1000
    assert dev_row["out_tokens"] == 200
    assert dev_row["calls"] == 1

    careledger_row = rows["careledger"]
    assert careledger_row["in_tokens"] == 2500  # 2000 + 500
    assert careledger_row["out_tokens"] == 500  # 400 + 100
    assert careledger_row["calls"] == 2
