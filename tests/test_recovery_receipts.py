from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_ledger.recovery.adapters.codex import CodexAdapter
from agent_ledger.recovery.catalog import RecoveryCatalog
from agent_ledger.recovery.discovery import AdapterRoot, discover_sessions
from agent_ledger.recovery.models import (
    HandoffStatus,
    ReceiptApplicability,
    RecoveryPackage,
    VerificationOutcome,
)
from agent_ledger.recovery.package import (
    assemble_recovery_package,
    recovery_brief_digest,
)
from agent_ledger.recovery.receipts import (
    ReceiptIntegrityError,
    ReceiptStore,
    fingerprint_repository,
    receipt_applicability,
    run_verification,
)


def _init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "demo@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Recovery Test"],
        check=True,
    )
    (path / "tracked.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "--", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-qm", "seed"],
        check=True,
    )


def _catalog(repo: Path, root: Path) -> tuple[RecoveryCatalog, str]:
    transcript = root / "rollout.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {
                    "timestamp": "2026-07-18T00:00:00Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "package-session",
                        "cwd": str(repo),
                        "timestamp": "2026-07-18T00:00:00Z",
                    },
                },
                {
                    "timestamp": "2026-07-18T00:00:01Z",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "Recover safely."},
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    adapter = CodexAdapter()
    discovered = discover_sessions(
        repo=repo,
        roots=(AdapterRoot(adapter=adapter, root=root),),
    )
    catalog = RecoveryCatalog(
        repo=repo,
        discovery=discovered,
        adapters=(adapter,),
    )
    return catalog, discovered.sessions[0].candidate.candidate_id


def test_repository_fingerprint_detects_content_drift_with_same_status(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "tracked.txt").write_text("first change\n", encoding="utf-8")
    first = fingerprint_repository(repo)
    (repo / "tracked.txt").write_text("second change\n", encoding="utf-8")
    second = fingerprint_repository(repo)
    subprocess.run(["git", "-C", str(repo), "add", "--", "tracked.txt"], check=True)
    staged = fingerprint_repository(repo)
    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    untracked = fingerprint_repository(repo)

    assert first.available is True
    assert first.digest != second.digest
    assert second.digest != staged.digest
    assert staged.digest != untracked.digest


def test_verification_records_only_process_outcome_and_redacted_command_metadata(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    private_value = "fixture-private-argv-and-output"

    receipt = run_verification(
        repo=repo,
        candidate_id="ses-test",
        brief_digest="a" * 64,
        owner_label="owner annotation",
        argv=(
            sys.executable,
            "-c",
            f"print('{private_value}')",
        ),
        timeout_seconds=5,
    )
    serialized = receipt.model_dump_json()

    assert receipt.outcome is VerificationOutcome.exited_zero
    assert receipt.exit_code == 0
    assert receipt.executable == Path(sys.executable).resolve().name
    assert receipt.argument_count == 2
    assert private_value not in serialized
    assert "print(" not in serialized
    assert receipt.repository_before.digest == receipt.repository_after.digest


def test_verification_records_nonzero_and_timeout_without_output(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    failed = run_verification(
        repo=repo,
        candidate_id="ses-test",
        brief_digest="b" * 64,
        owner_label="failed attempt",
        argv=(sys.executable, "-c", "raise SystemExit(7)"),
        timeout_seconds=5,
    )
    timed_out = run_verification(
        repo=repo,
        candidate_id="ses-test",
        brief_digest="b" * 64,
        owner_label="timeout attempt",
        argv=(sys.executable, "-c", "import time; time.sleep(10)"),
        timeout_seconds=0.1,
    )

    assert failed.outcome is VerificationOutcome.exited_nonzero
    assert failed.exit_code == 7
    assert timed_out.outcome is VerificationOutcome.timeout
    assert timed_out.exit_code is None
    assert "time.sleep" not in timed_out.model_dump_json()


def test_receipt_store_is_private_latest_attempt_wins_and_tampering_fails(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    store = ReceiptStore(tmp_path / "private-store")
    passed = run_verification(
        repo=repo,
        candidate_id="ses-test",
        brief_digest="c" * 64,
        owner_label="pass",
        argv=(sys.executable, "-c", "pass"),
        timeout_seconds=5,
    )
    failed = run_verification(
        repo=repo,
        candidate_id="ses-test",
        brief_digest="c" * 64,
        owner_label="fail",
        argv=(sys.executable, "-c", "raise SystemExit(2)"),
        timeout_seconds=5,
    )
    first_path = store.save(passed)
    second_path = store.save(failed)

    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(first_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(second_path.stat().st_mode) == 0o600
    assert store.latest("ses-test").receipt_id == failed.receipt_id

    payload = json.loads(second_path.read_text(encoding="utf-8"))
    payload["owner_label"] = "tampered"
    second_path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(second_path, 0o600)
    with pytest.raises(ReceiptIntegrityError):
        store.latest("ses-test")


def test_receipt_applicability_becomes_stale_on_brief_or_repository_drift(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    receipt = run_verification(
        repo=repo,
        candidate_id="ses-test",
        brief_digest="d" * 64,
        owner_label="current",
        argv=(sys.executable, "-c", "pass"),
        timeout_seconds=5,
    )

    assert (
        receipt_applicability(
            receipt,
            candidate_id="ses-test",
            brief_digest="d" * 64,
            current=fingerprint_repository(repo),
        )
        is ReceiptApplicability.current
    )
    assert (
        receipt_applicability(
            receipt,
            candidate_id="ses-test",
            brief_digest="e" * 64,
            current=fingerprint_repository(repo),
        )
        is ReceiptApplicability.stale
    )
    (repo / "untracked.txt").write_text("drift\n", encoding="utf-8")
    assert (
        receipt_applicability(
            receipt,
            candidate_id="ses-test",
            brief_digest="d" * 64,
            current=fingerprint_repository(repo),
        )
        is ReceiptApplicability.stale
    )


def test_recovery_package_reports_missing_then_current_and_checks_components(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    catalog, candidate_id = _catalog(repo, tmp_path / "sessions")
    store = ReceiptStore(tmp_path / "receipts")

    missing = assemble_recovery_package(
        catalog=catalog,
        candidate_id=candidate_id,
        store=store,
    )
    brief = catalog.recover(candidate_id)
    receipt = run_verification(
        repo=repo,
        candidate_id=candidate_id,
        brief_digest=recovery_brief_digest(brief),
        owner_label="package verification",
        argv=(sys.executable, "-c", "pass"),
        timeout_seconds=5,
    )
    store.save(receipt)
    current = assemble_recovery_package(
        catalog=catalog,
        candidate_id=candidate_id,
        store=store,
    )

    assert missing.handoff_status is HandoffStatus.missing
    assert current.handoff_status is HandoffStatus.current_exit_zero
    assert current.receipt_applicability is ReceiptApplicability.current
    assert set(current.component_checksums) == {"brief", "prompt", "receipt"}
    tampered = current.model_dump(mode="json")
    tampered["component_checksums"]["prompt"] = "0" * 64
    with pytest.raises(ValidationError):
        RecoveryPackage.model_validate(tampered)
