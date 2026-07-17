"""Provider-neutral structural evidence and adapter protocol."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from agent_ledger.recovery.models import CandidateEnding, SourceAdapter


class ResultStatus(StrEnum):
    """Conservative status of a recorded tool attempt."""

    recorded = "recorded"
    error = "error"
    missing = "missing"


class EvidenceModel(BaseModel):
    """Immutable internal evidence model."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolAttempt(EvidenceModel):
    """A tool invocation stripped of untrusted input and output bodies."""

    tool_use_id: str
    name: str
    line_number: int
    result_status: ResultStatus
    result_line_number: int | None = None


class TouchedPath(EvidenceModel):
    """An untrusted path named by a known file-touching tool."""

    path: str
    line_number: int
    tool_use_id: str


class TranscriptEvidence(EvidenceModel):
    """Normalized structural evidence consumed by the recovery assembler."""

    source_adapter: SourceAdapter
    provider: str
    session_id: str
    project: str
    intent: str
    last_timestamp: str
    recorded_cwd: str | None
    tool_attempts: tuple[ToolAttempt, ...]
    touched_paths: tuple[TouchedPath, ...]
    skipped_lines: int


class AdapterSession(EvidenceModel):
    """Private source metadata used before repository binding."""

    source_adapter: SourceAdapter
    provider: str
    source_session_id: str
    project_hint: str
    recorded_cwd: str | None
    started_at: datetime
    updated_at: datetime
    ending: CandidateEnding
    unmatched_call_count: int


class RecoveryAdapter(Protocol):
    """Contract each provider-specific local transcript adapter implements."""

    provider: str
    source_adapter: SourceAdapter

    def iter_sources(self, root: Path) -> tuple[Path, ...]:
        """Return candidate transcript files beneath a configured root."""

    def inspect(self, path: Path) -> AdapterSession:
        """Return privacy-redacted metadata used for discovery and binding."""

    def extract(self, path: Path) -> TranscriptEvidence:
        """Return normalized structural evidence without raw call bodies."""
