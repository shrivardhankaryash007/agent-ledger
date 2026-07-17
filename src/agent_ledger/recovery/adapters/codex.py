"""Structural adapter for local Codex rollout JSONL."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from agent_ledger.recovery.adapters.base import (
    AdapterSession,
    ResultStatus,
    ToolAttempt,
    TranscriptEvidence,
)
from agent_ledger.recovery.models import CandidateEnding, SourceAdapter
from agent_ledger.resume.detector import parse_timestamp

CODEX_SOURCE_ADAPTER = SourceAdapter(name="codex-jsonl", version=1)
CALL_TYPES = frozenset({"custom_tool_call", "function_call"})
OUTPUT_TYPES = frozenset({"custom_tool_call_output", "function_call_output"})


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


def _payload(record: dict[object, object]) -> dict[object, object] | None:
    value = record.get("payload")
    return cast("dict[object, object]", value) if isinstance(value, dict) else None


def _normalized_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_timestamp(value)
    except ValueError:
        return None


def _file_timestamp(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


class CodexAdapter:
    """Read local Codex event envelopes without retaining private call bodies."""

    provider = "codex"
    source_adapter = CODEX_SOURCE_ADAPTER

    def iter_sources(self, root: Path) -> tuple[Path, ...]:
        """Return JSONL rollout candidates beneath the configured sessions root."""

        if not root.is_dir():
            return ()
        return tuple(sorted(path for path in root.rglob("*.jsonl") if path.is_file()))

    def _parse(
        self, path: Path
    ) -> tuple[TranscriptEvidence, CandidateEnding, datetime]:
        records, skipped = _decode_lines(path)
        session_id = path.stem
        recorded_cwd: str | None = None
        intent = "No user intent was recoverable from the transcript."
        timestamps: list[datetime] = []
        attempts: list[tuple[str, str, int]] = []
        results: dict[str, tuple[ResultStatus, int]] = {}
        task_completed = False

        for line_number, record in records:
            envelope_timestamp = _normalized_timestamp(record.get("timestamp"))
            if envelope_timestamp is not None:
                timestamps.append(envelope_timestamp)
            payload = _payload(record)
            if payload is None:
                continue
            payload_timestamp = _normalized_timestamp(payload.get("timestamp"))
            if payload_timestamp is not None:
                timestamps.append(payload_timestamp)
            envelope_type = record.get("type")
            payload_type = payload.get("type")

            if envelope_type == "session_meta":
                candidate_id = payload.get("session_id") or payload.get("id")
                if isinstance(candidate_id, str) and candidate_id:
                    session_id = candidate_id
                cwd = payload.get("cwd")
                if isinstance(cwd, str) and cwd:
                    recorded_cwd = cwd
                continue

            if envelope_type == "event_msg":
                if payload_type == "task_complete":
                    task_completed = True
                if payload_type == "user_message" and intent.startswith("No user"):
                    message = payload.get("message")
                    if isinstance(message, str) and message.strip():
                        intent = message.strip()
                continue

            if envelope_type != "response_item" or not isinstance(payload_type, str):
                continue
            call_id = payload.get("call_id")
            if not isinstance(call_id, str) or not call_id:
                continue
            if payload_type in CALL_TYPES:
                name = payload.get("name")
                if isinstance(name, str) and name:
                    attempts.append((call_id, name, line_number))
            elif payload_type in OUTPUT_TYPES:
                status = (
                    ResultStatus.error
                    if payload.get("is_error") is True
                    else ResultStatus.recorded
                )
                results.setdefault(call_id, (status, line_number))

        tool_attempts = tuple(
            ToolAttempt(
                tool_use_id=call_id,
                name=name,
                line_number=line_number,
                result_status=results.get(call_id, (ResultStatus.missing, 0))[0],
                result_line_number=(
                    results[call_id][1] if call_id in results else None
                ),
            )
            for call_id, name, line_number in attempts
        )
        unmatched = sum(
            attempt.result_status is ResultStatus.missing for attempt in tool_attempts
        )
        ending = (
            CandidateEnding.interrupted
            if unmatched
            else CandidateEnding.completed
            if task_completed
            else CandidateEnding.unknown
        )
        updated_at = max(timestamps, default=_file_timestamp(path))
        evidence = TranscriptEvidence(
            source_adapter=self.source_adapter,
            provider=self.provider,
            session_id=session_id,
            project=(Path(recorded_cwd).name if recorded_cwd else path.parent.name),
            intent=intent,
            last_timestamp=updated_at.isoformat(),
            recorded_cwd=recorded_cwd,
            tool_attempts=tool_attempts,
            touched_paths=(),
            skipped_lines=skipped,
        )
        return evidence, ending, min(timestamps, default=updated_at)

    def inspect(self, path: Path) -> AdapterSession:
        """Return private binding metadata and redacted public candidate facts."""

        evidence, ending, started_at = self._parse(path)
        return AdapterSession(
            source_adapter=self.source_adapter,
            provider=self.provider,
            source_session_id=evidence.session_id,
            project_hint=evidence.project,
            recorded_cwd=evidence.recorded_cwd,
            started_at=started_at,
            updated_at=parse_timestamp(evidence.last_timestamp),
            ending=ending,
            unmatched_call_count=sum(
                attempt.result_status is ResultStatus.missing
                for attempt in evidence.tool_attempts
            ),
        )

    def extract(self, path: Path) -> TranscriptEvidence:
        """Extract normalized Codex evidence using exact call-ID pairing."""

        evidence, _, _ = self._parse(path)
        return evidence
