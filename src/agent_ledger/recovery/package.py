"""Canonical recovery package assembly with concurrent-drift protection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent_ledger.recovery.models import (
    HandoffStatus,
    ReceiptApplicability,
    ReceiptStatus,
    RecoveryPackage,
    VerificationOutcome,
    canonical_digest,
)
from agent_ledger.recovery.prompt import render_recovery_prompt
from agent_ledger.recovery.receipts import (
    fingerprint_repository,
    receipt_applicability,
)

if TYPE_CHECKING:
    from agent_ledger.recovery.catalog import RecoveryCatalog
    from agent_ledger.recovery.models import RecoveryBrief, RecoveryReceipt
    from agent_ledger.recovery.receipts import ReceiptStore


class ConcurrentRepositoryDriftError(RuntimeError):
    """Raised when repository content changes during package assembly."""


def recovery_brief_digest(brief: RecoveryBrief) -> str:
    """Bind receipts to evidence content while excluding generation time."""

    return canonical_digest(brief.model_dump(mode="json", exclude={"generated_at"}))


def _handoff_status(
    receipt: RecoveryReceipt | None,
    applicability: ReceiptApplicability,
) -> HandoffStatus:
    if receipt is None or applicability is ReceiptApplicability.missing:
        return HandoffStatus.missing
    if applicability is ReceiptApplicability.stale:
        return HandoffStatus.stale
    return {
        VerificationOutcome.exited_zero: HandoffStatus.current_exit_zero,
        VerificationOutcome.exited_nonzero: HandoffStatus.failed,
        VerificationOutcome.timeout: HandoffStatus.timeout,
        VerificationOutcome.error: HandoffStatus.error,
    }[receipt.outcome]


def receipt_status(
    *,
    catalog: RecoveryCatalog,
    candidate_id: str,
    store: ReceiptStore,
) -> ReceiptStatus:
    """Reread latest receipt and compute applicability against current state."""

    brief = catalog.recover(candidate_id)
    latest = store.latest(candidate_id)
    applicability = receipt_applicability(
        latest,
        candidate_id=candidate_id,
        brief_digest=recovery_brief_digest(brief),
        current=fingerprint_repository(catalog.trusted_repo),
    )
    return ReceiptStatus(latest_receipt=latest, applicability=applicability)


def assemble_recovery_package(
    *,
    catalog: RecoveryCatalog,
    candidate_id: str,
    store: ReceiptStore,
    exported_at: datetime | None = None,
) -> RecoveryPackage:
    """Assemble one canonical package only across a stable repository snapshot."""

    before = fingerprint_repository(catalog.trusted_repo)
    brief = catalog.recover(candidate_id)
    prompt = render_recovery_prompt(brief)
    latest = store.latest(candidate_id)
    brief_digest = recovery_brief_digest(brief)
    applicability = receipt_applicability(
        latest,
        candidate_id=candidate_id,
        brief_digest=brief_digest,
        current=before,
    )
    after = fingerprint_repository(catalog.trusted_repo)
    if before.digest != after.digest:
        raise ConcurrentRepositoryDriftError
    checksums = {
        "brief": canonical_digest(brief.model_dump(mode="json")),
        "prompt": canonical_digest(prompt),
    }
    if latest is not None:
        checksums["receipt"] = canonical_digest(latest.model_dump(mode="json"))
    return RecoveryPackage(
        exported_at=exported_at or datetime.now(UTC),
        handoff_status=_handoff_status(latest, applicability),
        brief=brief,
        prompt=prompt,
        latest_receipt=latest,
        receipt_applicability=applicability,
        component_checksums=checksums,
    )
