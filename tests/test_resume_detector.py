"""Unit tests for the resume ending detector."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agent_ledger.resume.detector import detect_ending
from agent_ledger.resume.models import SessionEnding


def create_fixture(tmp_path: Path, filename: str, lines: list[dict]) -> Path:
    """Create a temporary JSONL transcript file."""
    path = tmp_path / filename
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return path


def test_completed_graceful_mode(tmp_path: Path) -> None:
    """Test a session that ends gracefully with a mode: normal event."""
    lines = [
        {
            "type": "user",
            "message": "hello",
            "timestamp": "2026-07-06T10:00:00Z",
            "cwd": "/repo",
        },
        {"type": "assistant", "message": "hi", "timestamp": "2026-07-06T10:01:00Z"},
        {"type": "mode", "mode": "normal", "timestamp": "2026-07-06T10:02:00Z"},
    ]
    path = create_fixture(tmp_path, "session1.jsonl", lines)
    assert detect_ending(path) == SessionEnding.completed


def test_completed_graceful_title(tmp_path: Path) -> None:
    """Test a session that ends gracefully with an ai-title event."""
    lines = [
        {"type": "user", "message": "hello", "timestamp": "2026-07-06T10:00:00Z"},
        {"type": "ai-title", "aiTitle": "title", "timestamp": "2026-07-06T10:02:00Z"},
    ]
    path = create_fixture(tmp_path, "session2.jsonl", lines)
    assert detect_ending(path) == SessionEnding.completed


def test_completed_graceful_prompt(tmp_path: Path) -> None:
    """Test a session that ends gracefully with a last-prompt event."""
    lines = [
        {"type": "user", "message": "hello", "timestamp": "2026-07-06T10:00:00Z"},
        {
            "type": "last-prompt",
            "lastPrompt": "prompt",
            "timestamp": "2026-07-06T10:02:00Z",
        },
    ]
    path = create_fixture(tmp_path, "session3.jsonl", lines)
    assert detect_ending(path) == SessionEnding.completed


def test_interrupted_limit_429(tmp_path: Path) -> None:
    """Test a session that gets interrupted with a 429 status code."""
    lines = [
        {"type": "user", "message": "do work", "timestamp": "2026-07-06T10:00:00Z"},
        {
            "type": "assistant",
            "message": "working",
            "timestamp": "2026-07-06T10:01:00Z",
            "apiErrorStatus": 429,
        },
    ]
    path = create_fixture(tmp_path, "session4.jsonl", lines)
    assert detect_ending(path) == SessionEnding.interrupted_limit


def test_interrupted_limit_keyword(tmp_path: Path) -> None:
    """Test a session that gets interrupted with a rate limit keyword in error."""
    lines = [
        {"type": "user", "message": "do work", "timestamp": "2026-07-06T10:00:00Z"},
        {
            "type": "assistant",
            "message": "working",
            "timestamp": "2026-07-06T10:01:00Z",
            "error": "rate_limit_error: usage exceeded",
        },
    ]
    path = create_fixture(tmp_path, "session5.jsonl", lines)
    assert detect_ending(path) == SessionEnding.interrupted_limit


def test_interrupted_abort_connection(tmp_path: Path) -> None:
    """Test a session that ends due to connection abort in tail."""
    lines = [
        {"type": "user", "message": "do work", "timestamp": "2026-07-06T10:00:00Z"},
        {
            "type": "assistant",
            "message": "working",
            "timestamp": "2026-07-06T10:01:00Z",
            "error": "ECONNRESET: socket closed unexpectedly",
        },
    ]
    path = create_fixture(tmp_path, "session6.jsonl", lines)
    assert detect_ending(path) == SessionEnding.interrupted_abort


def test_interrupted_abort_no_commit(tmp_path: Path) -> None:
    """Test an ungraceful ending with no matching git commits."""
    lines = [
        {
            "type": "user",
            "message": "hello",
            "timestamp": "2026-07-06T10:00:00Z",
            "cwd": "/repo",
        },
        {"type": "assistant", "message": "hi", "timestamp": "2026-07-06T10:01:00Z"},
    ]
    path = create_fixture(tmp_path, "session7.jsonl", lines)
    with patch(
        "agent_ledger.resume.detector._has_matching_git_commit", return_value=False
    ):
        assert detect_ending(path) == SessionEnding.interrupted_abort


def test_completed_by_git_commit(tmp_path: Path) -> None:
    """Test that an ungraceful tail is healed to completed if git commit matches."""
    lines = [
        {
            "type": "user",
            "message": "hello",
            "timestamp": "2026-07-06T10:00:00Z",
            "cwd": "/repo",
        },
        {"type": "assistant", "message": "hi", "timestamp": "2026-07-06T10:01:00Z"},
    ]
    path = create_fixture(tmp_path, "session8.jsonl", lines)
    with patch(
        "agent_ledger.resume.detector._has_matching_git_commit", return_value=True
    ):
        assert detect_ending(path) == SessionEnding.completed


def test_unknown_empty_file(tmp_path: Path) -> None:
    """Test an empty session file results in unknown."""
    path = tmp_path / "empty.jsonl"
    path.touch()
    assert detect_ending(path) == SessionEnding.unknown


def test_unknown_no_timestamps(tmp_path: Path) -> None:
    """Test a session with no timestamp events results in unknown."""
    lines = [
        {"type": "user", "message": "hello"},
        {"type": "assistant", "message": "hi"},
    ]
    path = create_fixture(tmp_path, "session9.jsonl", lines)
    assert detect_ending(path) == SessionEnding.unknown
