"""Fix spec 2026-08-02 (agent-ledger fix spec v2), Fix 1 acceptance test.

Real transcript `cwd` values are launch/session directories that must
resolve to a git repo identity, not a directory basename. FAILS now
because `parse_transcript` still buckets by `Path(cwd).name`
(`ingest.git_label.resolve` exists but ingest doesn't call it yet).
Passes once `ingest.claude_transcripts` calls `git_label.resolve()` per
bucket and stops falling back to a bare basename — see
docs/decisions/0005-attribution-keys-on-git-identity.md.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_ledger.ingest.claude_transcripts import ingest
from agent_ledger.ledger.repository import all_records


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q"], cwd=path)
    _run(["git", "checkout", "-q", "-b", "main"], cwd=path)
    _run(
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
    )


def _write_transcript(path: Path, lines: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")


def test_worktree_session_rolls_up_to_parent_repo_name(tmp_path: Path) -> None:
    repo = tmp_path / "cosmos"
    _init_repo(repo)
    worktree = tmp_path / "cosmos-wt-epoch-milestones"
    _run(["git", "worktree", "add", "-q", "-b", "epoch", str(worktree)], cwd=repo)

    source_dir = tmp_path / "transcripts" / "-Users-yash-cosmos-wt-epoch-milestones"
    _write_transcript(
        source_dir / "sess-wt.jsonl",
        [
            {
                "sessionId": "sess-wt",
                "timestamp": "2026-08-01T10:00:00Z",
                "cwd": str(worktree),
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {"input_tokens": 1000, "output_tokens": 200},
                },
            }
        ],
    )

    db_path = tmp_path / "ledger.db"
    written = ingest(source_dir.parent, db_path)
    assert written == 1

    records = all_records(db_path)
    assert len(records) == 1
    record = records[0]

    # This is the whole point of the fix: a worktree session must roll up to
    # the parent repo, not fragment under its own worktree dir name.
    assert record.repo_name == "cosmos"
    assert record.worktree_name == "cosmos-wt-epoch-milestones"
    assert record.branch == "epoch"
    assert record.label_source == "git"
    assert record.project == "cosmos"


def test_non_repo_cwd_is_honestly_unattributed_not_a_guessed_basename(
    tmp_path: Path,
) -> None:
    not_a_repo = tmp_path / "just-a-folder"
    not_a_repo.mkdir()

    source_dir = tmp_path / "transcripts" / "-Users-yash-just-a-folder"
    _write_transcript(
        source_dir / "sess-plain.jsonl",
        [
            {
                "sessionId": "sess-plain",
                "timestamp": "2026-08-01T10:00:00Z",
                "cwd": str(not_a_repo),
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {"input_tokens": 500, "output_tokens": 100},
                },
            }
        ],
    )

    db_path = tmp_path / "ledger.db"
    ingest(source_dir.parent, db_path)

    records = all_records(db_path)
    assert len(records) == 1
    record = records[0]

    assert record.repo_name is None
    assert record.label_source == "not_a_repo"
    # The old bug: falling back to the cwd basename ("just-a-folder") and
    # calling that a project. Must not happen — honest "unknown" instead.
    assert record.project == "unknown"
    assert record.project != "just-a-folder"


def test_two_repos_in_one_session_split_into_two_records(tmp_path: Path) -> None:
    repo_a = tmp_path / "careledger"
    repo_b = tmp_path / "spandan"
    _init_repo(repo_a)
    _init_repo(repo_b)

    source_dir = tmp_path / "transcripts" / "-Users-yash-dev"
    _write_transcript(
        source_dir / "sess-mixed.jsonl",
        [
            {
                "sessionId": "sess-mixed",
                "timestamp": "2026-08-01T10:00:00Z",
                "cwd": str(repo_a),
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {"input_tokens": 1000, "output_tokens": 200},
                },
            },
            {
                "sessionId": "sess-mixed",
                "timestamp": "2026-08-01T10:05:00Z",
                "cwd": str(repo_b),
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {"input_tokens": 2000, "output_tokens": 400},
                },
            },
        ],
    )

    db_path = tmp_path / "ledger.db"
    ingest(source_dir.parent, db_path)

    records = {r.project: r for r in all_records(db_path)}
    assert set(records) == {"careledger", "spandan"}
    assert records["careledger"].repo_name == "careledger"
    assert records["spandan"].repo_name == "spandan"
    assert records["careledger"].label_source == "git"
    assert records["spandan"].label_source == "git"
