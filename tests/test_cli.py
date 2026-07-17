"""Unit tests for the typer CLI commands."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from agent_ledger.cli import app

runner = CliRunner()


def create_fixture(tmp_path: Path, filename: str, lines: list[dict]) -> Path:
    """Create a temporary JSONL transcript file.

    Creates parent directories if they don't exist.
    """
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return path


def test_cli_ingest_report_replay(tmp_path: Path) -> None:
    """Test ingest, report, and replay CLI commands with a temporary DB."""
    db_path = tmp_path / "test_ledger.db"

    # Create a dummy transcript directory
    transcripts_dir = tmp_path / "projects" / "test_proj"
    transcripts_dir.mkdir(parents=True)
    transcript_file = transcripts_dir / "session.jsonl"
    dummy_line = (
        '{"message": {"model": "claude-sonnet-5", '
        '"usage": {"input_tokens": 10, "output_tokens": 5}}, '
        '"sessionId": "s1", "timestamp": "2026-07-06T10:00:00Z"}\n'
    )
    transcript_file.write_text(dummy_line, encoding="utf-8")

    # Run ingest
    result = runner.invoke(
        app, ["ingest", str(transcripts_dir.parent), "--db-path", str(db_path)]
    )
    assert result.exit_code == 0
    assert "Ingested" in result.output

    # Run report
    result = runner.invoke(app, ["report", "--db-path", str(db_path)])
    assert result.exit_code == 0
    assert "test_proj" in result.output

    # Run replay
    result = runner.invoke(app, ["replay", "--db-path", str(db_path)])
    assert result.exit_code == 0
    assert "Actual spend:" in result.output


def test_cli_resume_list(tmp_path: Path) -> None:
    """Test resume --list CLI command."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # Create a couple of sessions
    s1_lines = [
        {
            "type": "user",
            "message": "hello",
            "timestamp": "2026-07-06T10:00:00Z",
            "cwd": "/repo1",
        },
        {"type": "mode", "mode": "normal", "timestamp": "2026-07-06T10:02:00Z"},
    ]
    s2_lines = [
        {
            "type": "user",
            "message": "hello",
            "timestamp": "2026-07-06T11:00:00Z",
            "cwd": "/repo2",
        },
        {"type": "assistant", "message": "hi", "timestamp": "2026-07-06T11:01:00Z"},
    ]
    create_fixture(projects_dir / "proj1", "s1.jsonl", s1_lines)
    create_fixture(projects_dir / "proj2", "s2.jsonl", s2_lines)

    # Run CLI resume --list
    with patch.dict(
        os.environ, {"AGENT_LEDGER_CLAUDE_PROJECTS_DIR": str(projects_dir)}
    ):
        result = runner.invoke(app, ["resume", "--list"])
        assert result.exit_code == 0
        assert "s1" in result.output
        assert "s2" in result.output
        assert "completed" in result.output
        assert "interrupted_abort" in result.output


def test_cli_resume_specific_and_default(tmp_path: Path) -> None:
    """Test resume command for specific session and fallback to default."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # Create one completed and one aborted session
    s1_lines = [
        {
            "type": "user",
            "message": "hello",
            "timestamp": "2026-07-06T10:00:00Z",
            "cwd": "/repo1",
        },
        {"type": "mode", "mode": "normal", "timestamp": "2026-07-06T10:02:00Z"},
    ]
    s2_lines = [
        {
            "type": "user",
            "message": "hello",
            "timestamp": "2026-07-06T11:00:00Z",
            "cwd": "/repo2",
        },
        {"type": "assistant", "message": "hi", "timestamp": "2026-07-06T11:01:00Z"},
    ]
    create_fixture(projects_dir / "proj1", "s1.jsonl", s1_lines)
    create_fixture(projects_dir / "proj2", "s2.jsonl", s2_lines)

    with patch.dict(
        os.environ, {"AGENT_LEDGER_CLAUDE_PROJECTS_DIR": str(projects_dir)}
    ):
        # 1. Specifying session that exists
        result = runner.invoke(app, ["resume", "--session", "s2"])
        assert result.exit_code == 0
        assert "Resuming specific session: s2" in result.output

        # 2. Specifying session that does NOT exist
        result = runner.invoke(app, ["resume", "--session", "missing_session"])
        assert result.exit_code == 1
        assert "Error: Session missing_session not found" in result.output

        # 3. Default path (should pick s2 because it is the most recent non-completed)
        result = runner.invoke(app, ["resume"])
        assert result.exit_code == 0
        assert "Most recent non-completed session: s2" in result.output


def test_cli_resume_no_non_completed(tmp_path: Path) -> None:
    """Test resume default path when there are only completed sessions."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    s1_lines = [
        {"type": "user", "message": "hello", "timestamp": "2026-07-06T10:00:00Z"},
        {"type": "mode", "mode": "normal", "timestamp": "2026-07-06T10:02:00Z"},
    ]
    create_fixture(projects_dir / "proj1", "s1.jsonl", s1_lines)

    with patch.dict(
        os.environ, {"AGENT_LEDGER_CLAUDE_PROJECTS_DIR": str(projects_dir)}
    ):
        result = runner.invoke(app, ["resume"])
        assert result.exit_code == 0
        assert "No non-completed sessions found to resume." in result.output


def test_cli_resume_missing_dir(tmp_path: Path) -> None:
    """Test resume CLI when projects directory is missing."""
    missing_dir = tmp_path / "non_existent_directory"

    with patch.dict(os.environ, {"AGENT_LEDGER_CLAUDE_PROJECTS_DIR": str(missing_dir)}):
        result = runner.invoke(app, ["resume"])
        assert result.exit_code == 1
        assert "Error: Claude projects directory not found" in result.output


def test_cli_recover_emits_json_and_safe_prompt(tmp_path: Path) -> None:
    """Recover emits either the versioned JSON contract or safe prompt."""

    projects_dir = tmp_path / "projects" / "demo"
    projects_dir.mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "demo@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Recovery Test"],
        check=True,
    )
    (repo / "safe.py").write_text("SAFE = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "safe.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True)
    create_fixture(
        projects_dir,
        "recover-me.jsonl",
        [
            {
                "type": "user",
                "sessionId": "recover-me",
                "timestamp": "2026-07-17T09:00:00Z",
                "message": {"role": "user", "content": "Continue safely."},
            },
            {
                "type": "assistant",
                "sessionId": "recover-me",
                "timestamp": "2026-07-17T09:01:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_test",
                            "name": "Bash",
                            "input": {"command": "private-command --secret value"},
                        }
                    ],
                },
            },
        ],
    )

    with patch.dict(
        os.environ,
        {"AGENT_LEDGER_CLAUDE_PROJECTS_DIR": str(tmp_path / "projects")},
    ):
        json_result = runner.invoke(
            app,
            [
                "recover",
                "--session",
                "recover-me",
                "--repo",
                str(repo),
                "--format",
                "json",
            ],
        )
        prompt_result = runner.invoke(
            app,
            [
                "recover",
                "--session",
                "recover-me",
                "--repo",
                str(repo),
                "--format",
                "prompt",
            ],
        )

    assert json_result.exit_code == 0
    assert json.loads(json_result.output)["brief_version"] == 1
    assert prompt_result.exit_code == 0
    assert "# Verified recovery brief" in prompt_result.output
    assert "private-command" not in json_result.output + prompt_result.output


def test_cli_demo_smoke_uses_disposable_server() -> None:
    """The demo command exposes a non-interactive smoke path."""

    result = runner.invoke(app, ["demo", "--no-open", "--smoke", "--port", "0"])

    assert result.exit_code == 0
    assert "Demo smoke passed" in result.output
