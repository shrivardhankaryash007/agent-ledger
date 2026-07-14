"""Deterministic local extraction of a resume packet from a Claude transcript."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from agent_ledger.ingest.claude_transcripts import (
    TranscriptLineStats,
    iter_transcript_lines,
)
from agent_ledger.resume.detector import detect_ending, parse_timestamp
from agent_ledger.resume.models import ResumePacket, SessionEnding

TOUCHING_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})


@dataclass(frozen=True)
class ExtractionResult:
    """A reconstructed packet and JSONL lines omitted during parsing."""

    packet: ResumePacket
    skipped_lines: int


def _record_timestamp(record: dict[object, object], fallback: datetime) -> datetime:
    """Return a usable record timestamp or a deterministic file-time fallback."""

    value = record.get("timestamp")
    if not isinstance(value, str):
        return fallback
    try:
        return parse_timestamp(value)
    except ValueError:
        return fallback


def _message(record: dict[object, object]) -> dict[object, object] | None:
    """Return the structured message payload when present."""

    value = record.get("message")
    return value if isinstance(value, dict) else None


def _text_content(value: object) -> list[str]:
    """Extract textual content from Claude's string or content-block encodings."""

    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    text: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        candidate = block.get("text")
        if isinstance(candidate, str) and candidate.strip():
            text.append(candidate.strip())
    return text


def _tool_blocks(record: dict[object, object]) -> list[dict[object, object]]:
    """Return tool-use blocks from one structured message."""

    message = _message(record)
    if message is None:
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [
        cast("dict[object, object]", block)
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


def _todos_from_tool(block: dict[object, object]) -> list[tuple[str, str]]:
    """Return unfinished TodoWrite items as ``(status, content)`` pairs."""

    if block.get("name") != "TodoWrite":
        return []
    input_value = block.get("input")
    if not isinstance(input_value, dict):
        return []
    todo_value = input_value.get("todos")
    if not isinstance(todo_value, list):
        return []
    todos: list[tuple[str, str]] = []
    for todo in todo_value:
        if not isinstance(todo, dict):
            continue
        content = todo.get("content")
        status = todo.get("status")
        if (
            isinstance(content, str)
            and content.strip()
            and isinstance(status, str)
            and status != "completed"
        ):
            todos.append((status, content.strip()))
    return todos


def _git_status(cwd: str | None) -> str:
    """Return concise git state, degrading to ``unavailable`` for any failure."""

    if not cwd:
        return "unavailable"
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    status = result.stdout.strip()
    return status if status else "clean"


def _fallback_action(last_state: str) -> list[str]:
    """Produce one safe next action when no unfinished plan item was recorded."""

    if last_state:
        return ["Review the last recorded state and continue the stated work."]
    return ["Inspect the transcript and working tree before resuming work."]


def extract_packet(
    transcript_path: Path, ending: SessionEnding | None = None
) -> ExtractionResult:
    """Build a deterministic resume packet from one local transcript.

    Args:
        transcript_path: Local Claude JSONL transcript.
        ending: Optional precomputed ending classification.

    Returns:
        Packet plus the count of malformed JSONL lines skipped by the shared parser.
    """

    fallback_time = datetime.fromtimestamp(transcript_path.stat().st_mtime, tz=UTC)
    stats = TranscriptLineStats()
    records = list(iter_transcript_lines(transcript_path, stats))
    session_id = transcript_path.stem
    project = transcript_path.parent.name
    cwd: str | None = None
    model_skus: list[str] = []
    intent = "No user intent was recoverable from the transcript."
    touched_files: list[str] = []
    bash_commands: list[str] = []
    final_assistant_text = (
        "No final assistant text was recoverable from the transcript."
    )
    unfinished_todos: list[tuple[str, str]] = []
    in_tokens = 0
    out_tokens = 0
    timestamps: list[datetime] = []

    for record in records:
        timestamps.append(_record_timestamp(record, fallback_time))
        record_session = record.get("sessionId")
        if isinstance(record_session, str) and record_session:
            session_id = record_session
        record_cwd = record.get("cwd")
        if isinstance(record_cwd, str) and record_cwd:
            cwd = record_cwd
            project = Path(cwd).name

        message = _message(record)
        if message is not None:
            model = message.get("model")
            if isinstance(model, str) and model and model not in model_skus:
                model_skus.append(model)
            usage = message.get("usage")
            if isinstance(usage, dict):
                input_tokens = usage.get("input_tokens")
                output_tokens = usage.get("output_tokens")
                if isinstance(input_tokens, int) and not isinstance(input_tokens, bool):
                    in_tokens += input_tokens
                if isinstance(output_tokens, int) and not isinstance(
                    output_tokens, bool
                ):
                    out_tokens += output_tokens

        if record.get("type") == "user" and intent.startswith("No user intent"):
            user_message = _message(record)
            if user_message is not None:
                text = _text_content(user_message.get("content"))
            else:
                text = _text_content(record.get("message"))
            if text:
                intent = text[0]

        if record.get("type") == "assistant" and message is not None:
            text = _text_content(message.get("content"))
            if text:
                final_assistant_text = "\n".join(text)

        for block in _tool_blocks(record):
            name = block.get("name")
            input_value = block.get("input")
            if name in TOUCHING_TOOLS and isinstance(input_value, dict):
                file_path = input_value.get("file_path") or input_value.get(
                    "notebook_path"
                )
                if (
                    isinstance(file_path, str)
                    and file_path
                    and file_path not in touched_files
                ):
                    touched_files.append(file_path)
            if name == "Bash" and isinstance(input_value, dict):
                command = input_value.get("command")
                if (
                    isinstance(command, str)
                    and command
                    and command not in bash_commands
                ):
                    bash_commands.append(command)
            todos = _todos_from_tool(block)
            if todos:
                unfinished_todos = todos

    last_state = final_assistant_text
    if unfinished_todos:
        todo_state = "\n".join(
            f"- [{status}] {content}" for status, content in unfinished_todos
        )
        last_state = f"{final_assistant_text}\n\nIn-flight todos:\n{todo_state}"
    next_actions = [
        content for _status, content in unfinished_todos
    ] or _fallback_action(final_assistant_text)
    started = min(timestamps, default=fallback_time)
    last_activity = max(timestamps, default=fallback_time)
    packet = ResumePacket(
        session_id=session_id,
        project=project,
        provider="claude-code",
        model_skus=model_skus,
        started=started,
        last_activity=last_activity,
        ending=ending if ending is not None else detect_ending(transcript_path),
        in_tokens=in_tokens,
        out_tokens=out_tokens,
        intent=intent,
        touched_files=touched_files,
        bash_commands=bash_commands,
        last_state=last_state,
        git_status=_git_status(cwd),
        next_actions=next_actions,
        source_path=str(transcript_path),
    )
    return ExtractionResult(packet=packet, skipped_lines=stats.skipped_lines)
