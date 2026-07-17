"""Assemble provider-specific evidence and current Git facts into a brief."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent_ledger.recovery.git_state import GitSnapshot, inspect_git
from agent_ledger.recovery.models import (
    Certainty,
    ContinuationAction,
    EvidenceKind,
    EvidenceRef,
    Observation,
    ReadinessCheck,
    ReadinessStatus,
    RecoveryBrief,
    SourceAdapter,
    Uncertainty,
)
from agent_ledger.resume.evidence import (
    ResultStatus,
    ToolAttempt,
    TranscriptEvidence,
    extract_transcript_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path

ADAPTER = SourceAdapter(name="claude-code-jsonl", version=1)


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _evidence_id(kind: EvidenceKind, locator: str) -> str:
    return f"ev-{_digest([ADAPTER.name, ADAPTER.version, kind, locator])[:16]}"


def _ref(
    kind: EvidenceKind, label: str, locator: str, digest_value: object
) -> EvidenceRef:
    return EvidenceRef(
        id=_evidence_id(kind, locator),
        kind=kind,
        label=label,
        locator=locator,
        digest=_digest(digest_value),
    )


def _attempt_ref(attempt: ToolAttempt) -> EvidenceRef:
    kind = (
        EvidenceKind.tool_result
        if attempt.result_status is not ResultStatus.missing
        else EvidenceKind.transcript
    )
    locator = f"line:{attempt.line_number}:tool:{attempt.tool_use_id}"
    return _ref(
        kind,
        f"Recorded {attempt.name} attempt",
        locator,
        {
            "tool_use_id": attempt.tool_use_id,
            "name": attempt.name,
            "line": attempt.line_number,
            "result": attempt.result_status,
            "result_line": attempt.result_line_number,
        },
    )


def _assemble_evidence(
    transcript: TranscriptEvidence, snapshot: GitSnapshot
) -> tuple[EvidenceRef, ...]:
    refs: list[EvidenceRef] = [
        _ref(
            EvidenceKind.transcript,
            "Session transcript envelope",
            "session:envelope",
            {
                "session_id": transcript.session_id,
                "project": transcript.project,
                "last_timestamp": transcript.last_timestamp,
                "skipped_lines": transcript.skipped_lines,
            },
        ),
        _ref(
            EvidenceKind.git,
            "Current Git snapshot",
            "git:head",
            {
                "repo": snapshot.repo_name,
                "branch": snapshot.branch,
                "head": snapshot.head,
                "clean": snapshot.worktree_clean,
            },
        ),
    ]
    refs.extend(_attempt_ref(attempt) for attempt in transcript.tool_attempts)
    refs.extend(
        _ref(
            EvidenceKind.git,
            f"Current state of {state.path}",
            f"git:path:{state.path}",
            {
                "path": state.path,
                "exists": state.exists,
                "differs": state.differs_from_head,
                "status": state.porcelain_status,
            },
        )
        for state in snapshot.path_states
    )
    return tuple(refs)


def _attempt_claims(
    transcript: TranscriptEvidence,
) -> tuple[list[Observation], list[Uncertainty]]:
    observations: list[Observation] = []
    uncertainties: list[Uncertainty] = []
    for index, attempt in enumerate(transcript.tool_attempts, start=1):
        evidence_id = _attempt_ref(attempt).id
        observations.append(
            Observation(
                id=f"recorded-attempt-{index}",
                statement=f"The transcript recorded a tool attempt: {attempt.name}.",
                certainty=Certainty.observed,
                evidence_ids=(evidence_id,),
            )
        )
        if attempt.result_status is ResultStatus.recorded:
            observations.append(
                Observation(
                    id=f"recorded-result-{index}",
                    statement=(
                        f"A non-error result was recorded for the {attempt.name} "
                        "attempt; current repository state is assessed separately."
                    ),
                    certainty=Certainty.observed,
                    evidence_ids=(evidence_id,),
                )
            )
        elif attempt.result_status is ResultStatus.error:
            observations.append(
                Observation(
                    id=f"recorded-error-{index}",
                    statement=f"The recorded {attempt.name} result was an error.",
                    certainty=Certainty.observed,
                    evidence_ids=(evidence_id,),
                )
            )
        else:
            uncertainties.append(
                Uncertainty(
                    id=f"missing-result-{index}",
                    statement=(
                        f"The recorded {attempt.name} attempt has no matching tool "
                        "result; its outcome is unknown."
                    ),
                    evidence_ids=(evidence_id,),
                )
            )
    return observations, uncertainties


def _path_claims(snapshot: GitSnapshot) -> list[Observation]:
    claims: list[Observation] = []
    for index, state in enumerate(snapshot.path_states, start=1):
        evidence_id = _evidence_id(EvidenceKind.git, f"git:path:{state.path}")
        if state.differs_from_head:
            statement = f"Current repository path '{state.path}' differs from HEAD."
        elif state.exists:
            statement = f"Current repository path '{state.path}' matches HEAD."
        else:
            statement = f"Current repository path '{state.path}' is absent."
        claims.append(
            Observation(
                id=f"current-path-{index}",
                statement=statement,
                certainty=Certainty.observed,
                evidence_ids=(evidence_id,),
            )
        )
    return claims


def _readiness(
    transcript: TranscriptEvidence, snapshot: GitSnapshot
) -> tuple[ReadinessCheck, ...]:
    git_evidence = _evidence_id(EvidenceKind.git, "git:head")
    checks: list[ReadinessCheck] = [
        ReadinessCheck(
            id="worktree",
            label="Current worktree",
            status=(
                ReadinessStatus.pass_
                if snapshot.worktree_clean
                else ReadinessStatus.warn
            ),
            detail=(
                "Worktree is clean."
                if snapshot.worktree_clean
                else "Worktree has current changes that must be reconciled."
            ),
            evidence_ids=(git_evidence,),
        )
    ]
    verification_attempts = [
        attempt for attempt in transcript.tool_attempts if attempt.name == "Bash"
    ]
    if not verification_attempts:
        checks.append(
            ReadinessCheck(
                id="verification",
                label="Recorded verification",
                status=ReadinessStatus.unknown,
                detail="No recorded verification attempt is available.",
                evidence_ids=(),
            )
        )
    else:
        statuses = {attempt.result_status for attempt in verification_attempts}
        if ResultStatus.error in statuses:
            status = ReadinessStatus.block
            detail = "A recorded verification result ended in error."
        elif ResultStatus.missing in statuses:
            status = ReadinessStatus.unknown
            detail = (
                "Verification is unknown: a recorded attempt has no matching result."
            )
        else:
            status = ReadinessStatus.warn
            detail = "A result was recorded, but verification is not current proof."
        checks.append(
            ReadinessCheck(
                id="verification",
                label="Recorded verification",
                status=status,
                detail=detail,
                evidence_ids=tuple(
                    _attempt_ref(item).id for item in verification_attempts
                ),
            )
        )
    checks.extend(
        ReadinessCheck(
            id=f"path-{index}",
            label=state.path,
            status=(
                ReadinessStatus.warn
                if state.differs_from_head
                else ReadinessStatus.pass_
                if state.exists
                else ReadinessStatus.block
            ),
            detail=(
                "Current file differs from HEAD."
                if state.differs_from_head
                else "Current file matches HEAD."
                if state.exists
                else "Recorded file is absent from the current worktree."
            ),
            evidence_ids=(_evidence_id(EvidenceKind.git, f"git:path:{state.path}"),),
        )
        for index, state in enumerate(snapshot.path_states, start=1)
    )
    return tuple(checks)


def _actions(needs_verification: bool) -> tuple[ContinuationAction, ...]:
    actions = [
        ContinuationAction(
            template_id="recovery.inspect-current-diff",
            position=1,
            instruction=(
                "Inspect the current diff for the recorded touched files "
                "before editing."
            ),
        )
    ]
    if needs_verification:
        actions.append(
            ContinuationAction(
                template_id="recovery.run-trusted-verification",
                position=2,
                instruction=(
                    "Run the project's trusted verification command from current "
                    "project instructions; do not assume the recorded command "
                    "succeeded."
                ),
            )
        )
    actions.append(
        ContinuationAction(
            template_id="recovery.reconcile-before-continuing",
            position=len(actions) + 1,
            instruction=(
                "Continue only after reconciling the current worktree with the "
                "recorded session intent."
            ),
        )
    )
    return tuple(actions)


def recover_session(
    transcript_path: Path,
    repo: Path,
    *,
    generated_at: datetime | None = None,
) -> RecoveryBrief:
    """Build a verified recovery brief from a local transcript and Git snapshot.

    Args:
        transcript_path: Local Claude Code JSONL transcript.
        repo: Owner-selected trusted repository path.
        generated_at: Optional deterministic generation time for tests and fixtures.

    Returns:
        Versioned recovery brief with linked evidence and safe actions.

    Raises:
        OSError: If the transcript cannot be read.
        RecoveryGitError: If the trusted repository cannot be inspected.
        UnsafeRecoveryPathError: If transcript path data is unsafe.
    """

    transcript = extract_transcript_evidence(transcript_path)
    snapshot = inspect_git(
        repo,
        tuple(item.path for item in transcript.touched_paths),
    )
    evidence = _assemble_evidence(transcript, snapshot)
    observations, uncertainties = _attempt_claims(transcript)
    observations.insert(
        0,
        Observation(
            id="recorded-intent",
            statement="A session intent was recorded in the transcript.",
            certainty=Certainty.observed,
            evidence_ids=(_evidence_id(EvidenceKind.transcript, "session:envelope"),),
        ),
    )
    observations.extend(_path_claims(snapshot))
    needs_verification = any(
        attempt.name == "Bash" and attempt.result_status is not ResultStatus.recorded
        for attempt in transcript.tool_attempts
    )
    return RecoveryBrief(
        generated_at=generated_at or datetime.now(UTC),
        session_id=transcript.session_id,
        project=transcript.project,
        repo_name=snapshot.repo_name,
        branch=snapshot.branch,
        head=snapshot.head,
        ending="unknown",
        intent=transcript.intent,
        source_adapter=ADAPTER,
        observations=tuple(observations),
        uncertainties=tuple(uncertainties),
        readiness=_readiness(transcript, snapshot),
        actions=_actions(needs_verification),
        evidence=evidence,
    )
