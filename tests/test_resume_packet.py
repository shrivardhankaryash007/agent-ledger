"""Regression tests for deterministic resume-packet extraction and rendering."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from hypothesis import given
from hypothesis import strategies as st

from agent_ledger.resume.extractor import extract_packet
from agent_ledger.resume.models import SessionEnding
from agent_ledger.resume.render import render_packet

if TYPE_CHECKING:
    import pytest


def _write_transcript(path: Path, lines: list[object]) -> Path:
    """Write a synthetic transcript, preserving malformed JSONL text."""

    path.write_text(
        "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines)
        + "\n",
        encoding="utf-8",
    )
    return path


def _fixture_lines() -> list[object]:
    """Return one synthetic interrupted session with all extraction signals."""

    return [
        {
            "type": "user",
            "sessionId": "resume-123",
            "timestamp": "2026-07-13T09:00:00Z",
            "cwd": "/work/agent-ledger",
            "message": {"content": "Build the resume packet renderer."},
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-13T09:01:00Z",
            "message": {
                "model": "claude-sonnet-5",
                "usage": {"input_tokens": 12, "output_tokens": 7},
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {"file_path": "src/agent_ledger/resume/render.py"},
                    },
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "pytest -q tests/test_resume_packet.py"},
                    },
                    {
                        "type": "tool_use",
                        "name": "TodoWrite",
                        "input": {
                            "todos": [
                                {
                                    "content": "Add renderer golden file",
                                    "status": "in_progress",
                                },
                                {"content": "Run project gate", "status": "pending"},
                            ]
                        },
                    },
                ],
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-13T09:02:00Z",
            "message": {
                "model": "claude-sonnet-5",
                "usage": {"input_tokens": 8, "output_tokens": 15},
                "content": (
                    "I implemented the renderer. Next I will run the project gate."
                ),
            },
        },
    ]


def test_extract_packet_and_render_golden(tmp_path: Path) -> None:
    """Extract a deterministic packet and render the handoff-contract schema."""

    transcript = _write_transcript(tmp_path / "resume-123.jsonl", _fixture_lines())
    result = extract_packet(transcript, ending=SessionEnding.interrupted_abort)

    assert result.skipped_lines == 0
    assert result.packet.intent == "Build the resume packet renderer."
    assert result.packet.touched_files == ["src/agent_ledger/resume/render.py"]
    assert result.packet.bash_commands == ["pytest -q tests/test_resume_packet.py"]
    assert result.packet.last_state == (
        "I implemented the renderer. Next I will run the project gate.\n\n"
        "In-flight todos:\n"
        "- [in_progress] Add renderer golden file\n"
        "- [pending] Run project gate"
    )
    assert result.packet.next_actions == [
        "Add renderer golden file",
        "Run project gate",
    ]
    assert result.packet.in_tokens == 20
    assert result.packet.out_tokens == 22

    expected = (Path(__file__).parent / "fixtures" / "resume_packet.md").read_text(
        encoding="utf-8"
    )
    assert render_packet(result.packet) == expected


def test_extractor_counts_malformed_jsonl_lines(tmp_path: Path) -> None:
    """Malformed JSONL lines are skipped and counted without aborting extraction."""

    transcript = _write_transcript(
        tmp_path / "malformed.jsonl",
        ["{not json", [], *_fixture_lines()],
    )

    result = extract_packet(transcript)

    assert result.skipped_lines == 2
    assert result.packet.intent == "Build the resume packet renderer."


@given(st.lists(st.text(max_size=200), max_size=25))
def test_extractor_never_raises_for_arbitrary_jsonl_lines(
    lines: list[str],
) -> None:
    """Arbitrary JSONL-like text must never make the extractor raise."""

    with tempfile.TemporaryDirectory() as directory:
        transcript = _write_transcript(Path(directory) / "arbitrary.jsonl", lines)

        result = extract_packet(transcript)

        assert result.skipped_lines >= 0
        assert result.packet.source_path == str(transcript)


def test_cli_resume_writes_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI writes the selected reconstructed packet to --out."""

    from typer.testing import CliRunner

    from agent_ledger.cli import app

    projects_dir = tmp_path / "projects" / "agent-ledger"
    projects_dir.mkdir(parents=True)
    _write_transcript(projects_dir / "resume-123.jsonl", _fixture_lines())
    output = tmp_path / "packet.md"
    monkeypatch.setenv("AGENT_LEDGER_CLAUDE_PROJECTS_DIR", str(projects_dir.parent))

    result = CliRunner().invoke(
        app, ["resume", "--session", "resume-123", "--out", str(output)]
    )

    assert result.exit_code == 0
    assert output.read_text(encoding="utf-8").startswith("---")
    assert "## Handoff Note" in output.read_text(encoding="utf-8")
