"""Declared recovery adapter for local Claude Code JSONL."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent_ledger.recovery.adapters.base import (
    AdapterSession,
    ResultStatus,
    TranscriptEvidence,
)
from agent_ledger.recovery.models import CandidateEnding
from agent_ledger.resume.detector import parse_timestamp
from agent_ledger.resume.evidence import (
    CLAUDE_SOURCE_ADAPTER,
    extract_transcript_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path


class ClaudeCodeAdapter:
    """Wrap the existing Claude evidence extractor behind the adapter protocol."""

    provider = "claude-code"
    source_adapter = CLAUDE_SOURCE_ADAPTER

    def iter_sources(self, root: Path) -> tuple[Path, ...]:
        """Return non-subagent JSONL transcripts beneath the configured root."""

        if not root.is_dir():
            return ()
        return tuple(
            sorted(
                path
                for path in root.rglob("*.jsonl")
                if path.is_file() and "subagents" not in path.parts
            )
        )

    def inspect(self, path: Path) -> AdapterSession:
        """Return private cwd binding metadata and redacted candidate facts."""

        evidence = self.extract(path)
        try:
            updated_at = parse_timestamp(evidence.last_timestamp)
        except ValueError:
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        unmatched = sum(
            attempt.result_status is ResultStatus.missing
            for attempt in evidence.tool_attempts
        )
        return AdapterSession(
            source_adapter=self.source_adapter,
            provider=self.provider,
            source_session_id=evidence.session_id,
            project_hint=evidence.project,
            recorded_cwd=evidence.recorded_cwd,
            started_at=updated_at,
            updated_at=updated_at,
            ending=(
                CandidateEnding.interrupted if unmatched else CandidateEnding.unknown
            ),
            unmatched_call_count=unmatched,
        )

    def extract(self, path: Path) -> TranscriptEvidence:
        """Delegate to the backward-compatible Claude evidence extractor."""

        return extract_transcript_evidence(path)
