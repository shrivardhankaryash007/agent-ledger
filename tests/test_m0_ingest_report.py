"""M0 acceptance test (docs/architecture.md), rescoped 2026-08-02.

'Real historical spend from existing Claude Code transcripts renders as a
per-project table.' Originally exercised via static fixtures with no `cwd`
field, attributing by `path.parent.name` — the exact mechanism the 2026-08-02
fix spec killed (86% of real spend had no usable label under it; see
docs/decisions/0005-attribution-keys-on-git-identity.md). This test now
builds real temporary git repos and transcripts that reference them as
`cwd`, and checks the same >=80% M0 kill criterion against git-resolved
attribution instead.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_ledger.ingest.claude_transcripts import ingest
from agent_ledger.report.spend import per_project


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-q", "-b", "main"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@test",
            "-c",
            "user.name=Test",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _write_jsonl(path: Path, lines: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")


def test_ingest_and_per_project_report(tmp_path: Path) -> None:
    dev_repo = tmp_path / "dev"
    careledger_repo = tmp_path / "careledger"
    _init_repo(dev_repo)
    _init_repo(careledger_repo)

    source_dir = tmp_path / "transcripts"
    _write_jsonl(
        source_dir / "-Users-yashshrivardhankar-dev" / "session-a.jsonl",
        [
            {
                "sessionId": "sess-a1",
                "timestamp": "2026-07-01T10:00:00Z",
                "cwd": str(dev_repo),
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {"input_tokens": 1000, "output_tokens": 200},
                },
            },
            {
                "sessionId": "sess-a1",
                "timestamp": "2026-07-01T10:05:00Z",
                "cwd": str(dev_repo),
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {"input_tokens": 500, "output_tokens": 100},
                },
            },
        ],
    )
    _write_jsonl(
        source_dir / "-Users-yashshrivardhankar-careledger" / "session-b.jsonl",
        [
            {
                "sessionId": "sess-b1",
                "timestamp": "2026-07-02T09:00:00Z",
                "cwd": str(careledger_repo),
                "message": {
                    "model": "claude-haiku-4-5",
                    "usage": {"input_tokens": 2000, "output_tokens": 300},
                },
            }
        ],
    )

    db_path = tmp_path / "ledger.db"
    written = ingest(source_dir, db_path)
    assert written == 2  # one CallRecord per (session, model): sess-a1, sess-b1

    frame = per_project(db_path)
    rows = {row["project"]: row for row in frame.to_dicts()}

    assert set(rows) == {"dev", "careledger"}

    dev_row = rows["dev"]
    assert dev_row["in_tokens"] == 1500  # 1000 + 500, both lines same session+model
    assert dev_row["out_tokens"] == 300  # 200 + 100
    assert dev_row["cost_usd"] == pytest.approx(0.009, rel=1e-6)

    careledger_row = rows["careledger"]
    assert careledger_row["in_tokens"] == 2000
    assert careledger_row["out_tokens"] == 300
    assert careledger_row["cost_usd"] == pytest.approx(0.0035, rel=1e-6)

    # M0 kill criterion (docs/architecture.md): >= 80% of records attributed
    # to a real project. Both fixture repos resolve via git, so this must be
    # 1.0 — a value below 0.8 on real data is the signal to stop and
    # rescope attribution instead of continuing (which is exactly what
    # happened on 2026-07-06, and again what the 2026-08-02 fix corrects).
    total_calls = sum(row["calls"] for row in rows.values())
    attributed_calls = sum(
        row["calls"] for row in rows.values() if row["project"] not in ("", "unknown")
    )
    assert attributed_calls / total_calls >= 0.8
