"""Versioned provider-neutral models for verified session recovery."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

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


class FingerprintState(StrEnum):
    """Whether repository content could be fingerprinted completely."""

    available = "available"
    unavailable = "unavailable"


class VerificationOutcome(StrEnum):
    """Observed process result without semantic interpretation."""

    exited_zero = "exited_zero"
    exited_nonzero = "exited_nonzero"
    error = "error"
    timeout = "timeout"


class ReceiptApplicability(StrEnum):
    """Whether a stored receipt still applies to current local evidence."""

    current = "current"
    stale = "stale"
    missing = "missing"


class HandoffStatus(StrEnum):
    """Portable package status derived from the latest receipt attempt."""

    current_exit_zero = "current_exit_zero"
    failed = "failed"
    timeout = "timeout"
    error = "error"
    stale = "stale"
    missing = "missing"


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


class SessionCatalog(RecoveryModel):
    """Repository-scoped candidate list safe for the Recovery Inbox."""

    repo_name: str
    sessions: tuple[SessionCandidate, ...]
    excluded_count: int = Field(ge=0)


def canonical_digest(value: object) -> str:
    """Return a stable SHA-256 digest for JSON-compatible public data."""

    payload = json.dumps(
        to_jsonable_python(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class RepositoryFingerprint(RecoveryModel):
    """Content-sensitive snapshot of one trusted Git worktree."""

    fingerprint_version: int = 1
    state: FingerprintState
    head: str | None = None
    staged_digest: str | None = None
    tracked_digest: str | None = None
    untracked_digest: str | None = None
    digest: str | None = None

    @property
    def available(self) -> bool:
        """Return whether all fingerprint components were observed."""

        return self.state is FingerprintState.available

    @model_validator(mode="after")
    def validate_availability(self) -> RepositoryFingerprint:
        """Require every digest exactly when the snapshot is available."""

        components = (
            self.head,
            self.staged_digest,
            self.tracked_digest,
            self.untracked_digest,
            self.digest,
        )
        if self.available != all(component is not None for component in components):
            raise ValueError("repository fingerprint availability is inconsistent")
        return self


class RecoveryReceipt(RecoveryModel):
    """Privacy-redacted record of one explicit local process attempt."""

    receipt_version: int = 1
    receipt_id: str
    brief_digest: str
    candidate_id: str
    owner_label: str = Field(min_length=1, max_length=160)
    executable: str
    executable_digest: str
    argv_digest: str
    argument_count: int = Field(ge=0)
    outcome: VerificationOutcome
    exit_code: int | None
    duration_ms: int = Field(ge=0)
    repository_before: RepositoryFingerprint
    repository_after: RepositoryFingerprint
    completed_at: datetime

    @field_validator("owner_label")
    @classmethod
    def validate_owner_label(cls, value: str) -> str:
        """Reject terminal and line-control injection in untrusted annotation."""

        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("owner label contains control characters")
        return value

    @model_validator(mode="after")
    def validate_receipt_id(self) -> RecoveryReceipt:
        """Bind the content-derived identifier to every persisted field."""

        payload = self.model_dump(mode="json", exclude={"receipt_id"})
        expected = f"rcp-{canonical_digest(payload)[:24]}"
        if self.receipt_id != expected:
            raise ValueError("receipt content digest does not match receipt ID")
        return self


class ReceiptStatus(RecoveryModel):
    """Latest receipt plus server-computed applicability."""

    latest_receipt: RecoveryReceipt | None
    applicability: ReceiptApplicability


class RecoveryPackage(RecoveryModel):
    """Canonical portable recovery handoff document."""

    package_version: int = 1
    exported_at: datetime
    handoff_status: HandoffStatus
    brief: RecoveryBrief
    prompt: str
    latest_receipt: RecoveryReceipt | None
    receipt_applicability: ReceiptApplicability
    component_checksums: dict[str, str]

    @model_validator(mode="after")
    def validate_component_checksums(self) -> RecoveryPackage:
        """Reject a package whose embedded component checksums disagree."""

        expected = {
            "brief": canonical_digest(self.brief.model_dump(mode="json")),
            "prompt": canonical_digest(self.prompt),
        }
        if self.latest_receipt is not None:
            expected["receipt"] = canonical_digest(
                self.latest_receipt.model_dump(mode="json")
            )
        if self.component_checksums != expected:
            raise ValueError("recovery package component checksum mismatch")
        return self


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


RecoveryPackage.model_rebuild()
