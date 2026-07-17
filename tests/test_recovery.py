from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_ledger.recovery.assembler import recover_session
from agent_ledger.recovery.git_state import UnsafeRecoveryPathError
from agent_ledger.recovery.models import RecoveryBrief
from agent_ledger.recovery.prompt import render_recovery_prompt
from agent_ledger.resume.evidence import (
    ResultStatus,
    extract_transcript_evidence,
)

FIXED_NOW = datetime(2026, 7, 17, 9, 30, tzinfo=UTC)


def _write_transcript(path: Path, content_blocks: list[dict[str, object]]) -> None:
    records = [
        {
            "type": "user",
            "sessionId": "session-recovery",
            "cwd": str(path.parent),
            "timestamp": "2026-07-17T09:00:00Z",
            "message": {"role": "user", "content": "Repair the verification flow."},
        },
        {
            "type": "assistant",
            "sessionId": "session-recovery",
            "cwd": str(path.parent),
            "timestamp": "2026-07-17T09:01:00Z",
            "message": {
                "role": "assistant",
                "model": "test-model",
                "content": content_blocks,
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )


def _append_result(
    path: Path, tool_use_id: str, *, is_error: bool | None = None
) -> None:
    block: dict[str, object] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": "private result body",
    }
    if is_error is not None:
        block["is_error"] = is_error
    record = {
        "type": "user",
        "sessionId": "session-recovery",
        "timestamp": "2026-07-17T09:02:00Z",
        "message": {"role": "user", "content": [block]},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(record))


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "demo@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Recovery Test"],
        check=True,
    )


def _commit_file(repo: Path, relative_path: str, content: str) -> None:
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "--", relative_path], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True)


def test_tool_results_pair_structurally_without_copying_private_content(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "session-recovery.jsonl"
    _write_transcript(
        transcript,
        [
            {
                "type": "tool_use",
                "id": "toolu_success",
                "name": "Bash",
                "input": {"command": "secret-verification-command --token hidden"},
            },
            {
                "type": "tool_use",
                "id": "toolu_error",
                "name": "Bash",
                "input": {"command": "another-private-command"},
            },
            {
                "type": "tool_use",
                "id": "toolu_missing",
                "name": "Bash",
                "input": {"command": "never-finished-command"},
            },
        ],
    )
    _append_result(transcript, "toolu_success")
    _append_result(transcript, "toolu_error", is_error=True)

    evidence = extract_transcript_evidence(transcript)

    assert [attempt.result_status for attempt in evidence.tool_attempts] == [
        ResultStatus.recorded,
        ResultStatus.error,
        ResultStatus.missing,
    ]
    serialized = evidence.model_dump_json()
    assert "secret-verification-command" not in serialized
    assert "private result body" not in serialized


def test_recovery_separates_recorded_attempt_from_current_git_state(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _commit_file(repo, "src/check.py", "STATE = 'before'\n")
    (repo / "src/check.py").write_text("STATE = 'after'\n", encoding="utf-8")

    transcript = tmp_path / "session-recovery.jsonl"
    _write_transcript(
        transcript,
        [
            {
                "type": "tool_use",
                "id": "toolu_edit",
                "name": "Edit",
                "input": {"file_path": "src/check.py"},
            },
            {
                "type": "tool_use",
                "id": "toolu_pytest",
                "name": "Bash",
                "input": {"command": "pytest --token raw-secret"},
            },
        ],
    )

    brief = recover_session(transcript, repo, generated_at=FIXED_NOW)
    payload = brief.model_dump_json()

    assert brief.brief_version == 1
    assert brief.source_adapter.name == "claude-code-jsonl"
    assert brief.source_adapter.version == 1
    assert any("recorded" in item.statement.lower() for item in brief.observations)
    assert any(
        "differs from head" in item.statement.lower() for item in brief.observations
    )
    assert any("unknown" in item.statement.lower() for item in brief.uncertainties)
    assert {check.status.value for check in brief.readiness} >= {"warn", "unknown"}
    assert "pytest --token raw-secret" not in payload
    assert "raw-secret" not in render_recovery_prompt(brief)
    assert all(action.template_id.startswith("recovery.") for action in brief.actions)

    evidence_ids = {item.id for item in brief.evidence}
    referenced_ids = {
        evidence_id
        for group in (brief.observations, brief.uncertainties, brief.readiness)
        for item in group
        for evidence_id in item.evidence_ids
    }
    assert referenced_ids <= evidence_ids


@pytest.mark.parametrize(
    "recorded_path",
    [
        "../outside.py",
        "/tmp/outside.py",
        "-dangerous-pathspec",
        "safe\\windows.py",
    ],
)
def test_recovery_rejects_untrusted_paths(tmp_path: Path, recorded_path: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _commit_file(repo, "safe.py", "SAFE = True\n")
    transcript = tmp_path / "session-recovery.jsonl"
    _write_transcript(
        transcript,
        [
            {
                "type": "tool_use",
                "id": "toolu_edit",
                "name": "Edit",
                "input": {"file_path": recorded_path},
            }
        ],
    )

    with pytest.raises(UnsafeRecoveryPathError):
        recover_session(transcript, repo, generated_at=FIXED_NOW)


def test_recovery_accepts_contained_absolute_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _commit_file(repo, "src/check.py", "STATE = 'before'\n")
    (repo / "src/check.py").write_text("STATE = 'after'\n", encoding="utf-8")
    transcript = tmp_path / "session-recovery.jsonl"
    _write_transcript(
        transcript,
        [
            {
                "type": "tool_use",
                "id": "toolu_edit",
                "name": "Edit",
                "input": {"file_path": str(repo / "src/check.py")},
            }
        ],
    )

    brief = recover_session(transcript, repo, generated_at=FIXED_NOW)

    assert any(
        "'src/check.py' differs from HEAD" in item.statement
        for item in brief.observations
    )


def test_recovery_rejects_absolute_path_in_same_named_sibling_repo(
    tmp_path: Path,
) -> None:
    trusted = tmp_path / "trusted" / "repo"
    trusted.parent.mkdir()
    trusted.mkdir()
    _init_repo(trusted)
    _commit_file(trusted, "safe.py", "SAFE = True\n")
    sibling = tmp_path / "sibling" / "repo"
    sibling.parent.mkdir()
    sibling.mkdir()
    _init_repo(sibling)
    _commit_file(sibling, "safe.py", "SAFE = False\n")
    transcript = tmp_path / "session-recovery.jsonl"
    _write_transcript(
        transcript,
        [
            {
                "type": "tool_use",
                "id": "toolu_edit",
                "name": "Edit",
                "input": {"file_path": str(sibling / "safe.py")},
            }
        ],
    )

    with pytest.raises(UnsafeRecoveryPathError):
        recover_session(transcript, trusted, generated_at=FIXED_NOW)


def test_recovery_rejects_symlink_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _commit_file(repo, "safe.py", "SAFE = True\n")
    outside = tmp_path / "outside.py"
    outside.write_text("PRIVATE = True\n", encoding="utf-8")
    (repo / "linked.py").symlink_to(outside)
    transcript = tmp_path / "session-recovery.jsonl"
    _write_transcript(
        transcript,
        [
            {
                "type": "tool_use",
                "id": "toolu_edit",
                "name": "Edit",
                "input": {"file_path": "linked.py"},
            }
        ],
    )

    with pytest.raises(UnsafeRecoveryPathError):
        recover_session(transcript, repo, generated_at=FIXED_NOW)


def test_recovery_json_is_deterministic_for_a_fixed_snapshot(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _commit_file(repo, "safe.py", "SAFE = True\n")
    transcript = tmp_path / "session-recovery.jsonl"
    _write_transcript(transcript, [])

    first = recover_session(transcript, repo, generated_at=FIXED_NOW)
    second = recover_session(transcript, repo, generated_at=FIXED_NOW)

    assert RecoveryBrief.model_validate_json(first.model_dump_json()) == first
    assert first.model_dump_json() == second.model_dump_json()


def test_recovery_does_not_use_transcript_cwd_for_git_ending_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _commit_file(repo, "safe.py", "SAFE = True\n")
    transcript = tmp_path / "session-recovery.jsonl"
    _write_transcript(transcript, [])

    def forbidden_git_inference(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("recovery must not trust transcript cwd for Git")

    monkeypatch.setattr(
        "agent_ledger.resume.detector._has_matching_git_commit",
        forbidden_git_inference,
    )

    brief = recover_session(transcript, repo, generated_at=FIXED_NOW)

    assert brief.ending == "unknown"
