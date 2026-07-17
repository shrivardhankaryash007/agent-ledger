"""Versioned provider-neutral models for verified session recovery."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

BRIEF_VERSION = 1


class EvidenceKind(StrEnum):
    """Local source classes that may support a recovery claim."""

    transcript = "transcript"
    tool_result = "tool_result"
    git = "git"


class Certainty(StrEnum):
    """Whether a claim is directly observed or cautiously inferred."""

    observed = "observed"
    inferred = "inferred"


class ReadinessStatus(StrEnum):
    """Status of a recovery readiness check."""

    pass_ = "pass"
    warn = "warn"
    block = "block"
    unknown = "unknown"


class CandidateEnding(StrEnum):
    """Coarse provider-neutral ending state for recovery discovery."""

    completed = "completed"
    interrupted = "interrupted"
    active = "active"
    unknown = "unknown"


class RecoveryModel(BaseModel):
    """Strict base model for the public recovery contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceAdapter(RecoveryModel):
    """Provider adapter identity independent of the recovery schema version."""

    name: str
    version: int = Field(ge=1)


class SessionCandidate(RecoveryModel):
    """Privacy-redacted session metadata safe for the Recovery Inbox."""

    candidate_id: str
    provider: str
    source_adapter: SourceAdapter
    source_session_id: str
    project_hint: str
    started_at: datetime
    updated_at: datetime
    ending: CandidateEnding
    unmatched_call_count: int = Field(ge=0)


class EvidenceRef(RecoveryModel):
    """Redacted locator and digest for one local evidence item."""

    id: str
    kind: EvidenceKind
    label: str
    locator: str
    digest: str


class Observation(RecoveryModel):
    """A supported statement about recorded or current state."""

    id: str
    statement: str
    certainty: Certainty
    evidence_ids: tuple[str, ...]


class Uncertainty(RecoveryModel):
    """A boundary the available evidence cannot safely cross."""

    id: str
    statement: str
    evidence_ids: tuple[str, ...]


class ReadinessCheck(RecoveryModel):
    """One explicit continuation gate."""

    id: str
    label: str
    status: ReadinessStatus
    detail: str
    evidence_ids: tuple[str, ...]


class ContinuationAction(RecoveryModel):
    """Application-authored safe continuation step."""

    template_id: str
    position: int = Field(ge=1)
    instruction: str


class RecoveryBrief(RecoveryModel):
    """Provider-neutral, evidence-linked recovery brief (v1)."""

    brief_version: int = BRIEF_VERSION
    generated_at: datetime
    session_id: str
    project: str
    repo_name: str
    branch: str
    head: str
    ending: str
    intent: str
    source_adapter: SourceAdapter
    observations: tuple[Observation, ...]
    uncertainties: tuple[Uncertainty, ...]
    readiness: tuple[ReadinessCheck, ...]
    actions: tuple[ContinuationAction, ...]
    evidence: tuple[EvidenceRef, ...]

    @model_validator(mode="after")
    def validate_evidence_links(self) -> RecoveryBrief:
        """Reject duplicate evidence IDs and dangling claim references."""

        known = [item.id for item in self.evidence]
        if len(known) != len(set(known)):
            raise ValueError("recovery evidence IDs must be unique")
        known_set = set(known)
        referenced = {
            evidence_id
            for collection in (
                self.observations,
                self.uncertainties,
                self.readiness,
            )
            for item in collection
            for evidence_id in item.evidence_ids
        }
        missing = sorted(referenced - known_set)
        if missing:
            raise ValueError(f"unknown recovery evidence IDs: {', '.join(missing)}")
        return self
