from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_ledger.recovery.adapters.base import ResultStatus
from agent_ledger.recovery.adapters.claude_code import ClaudeCodeAdapter
from agent_ledger.recovery.adapters.codex import CodexAdapter
from agent_ledger.recovery.assembler import recover_evidence
from agent_ledger.recovery.discovery import AdapterRoot, discover_sessions
from agent_ledger.recovery.models import CandidateEnding


def _init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def _codex_records(
    *,
    session_id: str,
    cwd: Path | None,
    include_calls: bool = True,
) -> list[dict[str, object]]:
    meta: dict[str, object] = {
        "id": session_id,
        "session_id": session_id,
        "timestamp": "2026-07-18T00:00:00Z",
        "source": "codex",
    }
    if cwd is not None:
        meta["cwd"] = str(cwd)
    records: list[dict[str, object]] = [
        {
            "timestamp": "2026-07-18T00:00:00Z",
            "type": "session_meta",
            "payload": meta,
        },
        {
            "timestamp": "2026-07-18T00:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": "Repair the interrupted verification flow.",
            },
        },
    ]
    if include_calls:
        records.extend(
            [
                {
                    "timestamp": "2026-07-18T00:00:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "call_id": "call-matched",
                        "name": "exec",
                        "status": "completed",
                        "input": "private-command --token fixture-secret",
                    },
                },
                {
                    "timestamp": "2026-07-18T00:00:03Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": "call-matched",
                        "output": "private-output fixture-secret",
                    },
                },
                {
                    "timestamp": "2026-07-18T00:00:04Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "call_id": "call-missing",
                        "name": "exec",
                        "status": "completed",
                        "input": "another-private-command",
                    },
                },
                {
                    "timestamp": "2026-07-18T00:00:05Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "call_id": "call-function",
                        "namespace": "collaboration",
                        "name": "wait_agent",
                        "arguments": '{"private":"fixture-secret"}',
                    },
                },
                {
                    "timestamp": "2026-07-18T00:00:06Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-function",
                        "output": "private-function-output",
                    },
                },
            ]
        )
    return records


def _claude_records(*, cwd: Path) -> list[dict[str, object]]:
    return [
        {
            "type": "user",
            "sessionId": "claude-session",
            "cwd": str(cwd),
            "timestamp": "2026-07-18T00:00:00Z",
            "message": {"role": "user", "content": "Repair recovery."},
        },
        {
            "type": "assistant",
            "sessionId": "claude-session",
            "cwd": str(cwd),
            "timestamp": "2026-07-18T00:00:01Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_missing",
                        "name": "Bash",
                        "input": {"command": "private-command"},
                    }
                ],
            },
        },
    ]


def test_codex_pairs_outputs_by_call_id_without_trusting_call_status(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    transcript = tmp_path / "sessions" / "rollout.jsonl"
    _write_jsonl(
        transcript,
        _codex_records(session_id="codex-session", cwd=repo),
    )

    evidence = CodexAdapter().extract(transcript)

    assert evidence.source_adapter.name == "codex-jsonl"
    assert [attempt.tool_use_id for attempt in evidence.tool_attempts] == [
        "call-matched",
        "call-missing",
        "call-function",
    ]
    assert [attempt.result_status for attempt in evidence.tool_attempts] == [
        ResultStatus.recorded,
        ResultStatus.missing,
        ResultStatus.recorded,
    ]


def test_codex_evidence_omits_private_call_bodies(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    transcript = tmp_path / "sessions" / "rollout.jsonl"
    _write_jsonl(
        transcript,
        _codex_records(session_id="codex-private", cwd=repo),
    )

    serialized = CodexAdapter().extract(transcript).model_dump_json()

    assert "fixture-secret" not in serialized
    assert "private-command" not in serialized
    assert "private-output" not in serialized
    assert "private-function-output" not in serialized


def test_claude_adapter_preserves_existing_extractor_contract(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    root = tmp_path / "claude-projects"
    transcript = root / "project" / "claude-session.jsonl"
    _write_jsonl(transcript, _claude_records(cwd=repo))
    subagent = root / "project" / "subagents" / "ignored.jsonl"
    _write_jsonl(subagent, _claude_records(cwd=repo))
    adapter = ClaudeCodeAdapter()

    assert adapter.iter_sources(root) == (transcript,)
    evidence = adapter.extract(transcript)
    inspected = adapter.inspect(transcript)

    assert evidence.source_adapter.name == "claude-code-jsonl"
    assert inspected.source_session_id == "claude-session"
    assert inspected.recorded_cwd == str(repo)
    assert inspected.ending is CandidateEnding.interrupted
    assert inspected.unmatched_call_count == 1
    assert "private-command" not in evidence.model_dump_json()


def test_provider_neutral_assembler_uses_codex_adapter_identity(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "safe.py").write_text("SAFE = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "--", "safe.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Recovery Test",
            "-c",
            "user.email=demo@example.invalid",
            "commit",
            "-qm",
            "seed",
        ],
        check=True,
    )
    transcript = tmp_path / "sessions" / "rollout.jsonl"
    _write_jsonl(
        transcript,
        _codex_records(session_id="codex-assembled", cwd=repo),
    )

    brief = recover_evidence(CodexAdapter().extract(transcript), repo)

    assert brief.source_adapter.name == "codex-jsonl"
    assert any("outcome is unknown" in item.statement for item in brief.uncertainties)


def test_discovery_excludes_unbound_and_mismatched_sessions(tmp_path: Path) -> None:
    trusted_repo = tmp_path / "trusted" / "same-name"
    trusted_repo.parent.mkdir()
    _init_repo(trusted_repo)
    other_repo = tmp_path / "other" / "same-name"
    other_repo.parent.mkdir()
    _init_repo(other_repo)
    sessions_root = tmp_path / "codex-sessions"
    _write_jsonl(
        sessions_root / "bound.jsonl",
        _codex_records(
            session_id="bound-session",
            cwd=trusted_repo,
            include_calls=False,
        ),
    )
    _write_jsonl(
        sessions_root / "mismatched.jsonl",
        _codex_records(
            session_id="mismatched-session",
            cwd=other_repo,
            include_calls=False,
        ),
    )
    _write_jsonl(
        sessions_root / "unbound.jsonl",
        _codex_records(
            session_id="unbound-session",
            cwd=None,
            include_calls=False,
        ),
    )

    result = discover_sessions(
        repo=trusted_repo,
        roots=(AdapterRoot(adapter=CodexAdapter(), root=sessions_root),),
        limit=10,
    )

    assert [item.candidate.source_session_id for item in result.sessions] == [
        "bound-session"
    ]
    assert result.excluded_count == 2
    serialized = result.sessions[0].candidate.model_dump_json()
    assert str(trusted_repo) not in serialized
    assert str(sessions_root) not in serialized
