"""Structural Claude transcript evidence extraction for recovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from agent_ledger.recovery.adapters.base import (
    ResultStatus,
    ToolAttempt,
    TouchedPath,
    TranscriptEvidence,
)
from agent_ledger.recovery.models import SourceAdapter
from agent_ledger.resume.detector import parse_timestamp

FILE_TOUCHING_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
CLAUDE_SOURCE_ADAPTER = SourceAdapter(name="claude-code-jsonl", version=1)


def _message(record: dict[object, object]) -> dict[object, object] | None:
    value = record.get("message")
    return cast("dict[object, object]", value) if isinstance(value, dict) else None


def _content_blocks(record: dict[object, object]) -> list[dict[object, object]]:
    message = _message(record)
    if message is None:
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [
        cast("dict[object, object]", item) for item in content if isinstance(item, dict)
    ]


def _user_text(record: dict[object, object]) -> str | None:
    message = _message(record)
    if message is None:
        return None
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def _decode_lines(path: Path) -> tuple[list[tuple[int, dict[object, object]]], int]:
    records: list[tuple[int, dict[object, object]]] = []
    skipped = 0
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        try:
            decoded: object = json.loads(raw_line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(decoded, dict):
            skipped += 1
            continue
        records.append((line_number, cast("dict[object, object]", decoded)))
    return records, skipped


def extract_transcript_evidence(path: Path) -> TranscriptEvidence:
    """Extract structural evidence without retaining commands or result bodies.

    Args:
        path: Local Claude Code JSONL transcript.

    Returns:
        A compact structural representation safe for recovery assembly.

    Raises:
        OSError: If the local transcript cannot be read.
    """

    records, skipped = _decode_lines(path)
    session_id = path.stem
    project = path.parent.name
    recorded_cwd: str | None = None
    intent = "No user intent was recoverable from the transcript."
    last_timestamp = ""
    attempts: list[tuple[str, str, int]] = []
    touched_paths: list[TouchedPath] = []
    results: dict[str, tuple[ResultStatus, int]] = {}

    for line_number, record in records:
        record_session = record.get("sessionId")
        if isinstance(record_session, str) and record_session:
            session_id = record_session
        cwd = record.get("cwd")
        if isinstance(cwd, str) and cwd:
            project = Path(cwd).name
            recorded_cwd = cwd
        timestamp = record.get("timestamp")
        if isinstance(timestamp, str):
            try:
                normalized = parse_timestamp(timestamp).isoformat()
            except ValueError:
                normalized = ""
            if normalized > last_timestamp:
                last_timestamp = normalized
        if record.get("type") == "user" and intent.startswith("No user intent"):
            recovered = _user_text(record)
            if recovered is not None:
                intent = recovered

        for block in _content_blocks(record):
            block_type = block.get("type")
            if block_type == "tool_use":
                tool_use_id = block.get("id")
                name = block.get("name")
                if not isinstance(tool_use_id, str) or not isinstance(name, str):
                    continue
                attempts.append((tool_use_id, name, line_number))
                input_value = block.get("input")
                if name not in FILE_TOUCHING_TOOLS or not isinstance(input_value, dict):
                    continue
                file_path = input_value.get("file_path") or input_value.get(
                    "notebook_path"
                )
                if isinstance(file_path, str) and file_path:
                    touched_paths.append(
                        TouchedPath(
                            path=file_path,
                            line_number=line_number,
                            tool_use_id=tool_use_id,
                        )
                    )
            elif block_type == "tool_result":
                tool_use_id = block.get("tool_use_id")
                if not isinstance(tool_use_id, str):
                    continue
                status = (
                    ResultStatus.error
                    if block.get("is_error") is True
                    else ResultStatus.recorded
                )
                results.setdefault(tool_use_id, (status, line_number))

    tool_attempts = tuple(
        ToolAttempt(
            tool_use_id=tool_use_id,
            name=name,
            line_number=line_number,
            result_status=results.get(tool_use_id, (ResultStatus.missing, 0))[0],
            result_line_number=(
                results[tool_use_id][1] if tool_use_id in results else None
            ),
        )
        for tool_use_id, name, line_number in attempts
    )
    return TranscriptEvidence(
        source_adapter=CLAUDE_SOURCE_ADAPTER,
        provider="claude-code",
        session_id=session_id,
        project=project,
        intent=intent,
        last_timestamp=last_timestamp,
        recorded_cwd=recorded_cwd,
        tool_attempts=tool_attempts,
        touched_paths=tuple(touched_paths),
        skipped_lines=skipped,
    )
