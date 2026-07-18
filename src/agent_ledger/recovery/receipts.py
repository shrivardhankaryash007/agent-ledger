"""Explicit verification execution, content fingerprints, and private receipts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agent_ledger.recovery.git_state import (
    RecoveryGitError,
    UnsafeRecoveryPathError,
    resolve_repo,
    validate_recovery_path,
)
from agent_ledger.recovery.models import (
    FingerprintState,
    ReceiptApplicability,
    RecoveryReceipt,
    RepositoryFingerprint,
    VerificationOutcome,
    canonical_digest,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

MAX_UNTRACKED_FILES = 2_000
MAX_UNTRACKED_FILE_BYTES = 16 * 1024 * 1024
MAX_UNTRACKED_TOTAL_BYTES = 64 * 1024 * 1024


class ReceiptIntegrityError(RuntimeError):
    """Raised when a private receipt fails schema or content-ID validation."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_bytes(root: Path, arguments: Sequence[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryGitError("trusted repository could not be fingerprinted") from exc
    return completed.stdout


def _untracked_digest(root: Path) -> str:
    listed = _git_bytes(root, ("ls-files", "--others", "--exclude-standard", "-z"))
    names = sorted(name for name in listed.split(b"\0") if name)
    if len(names) > MAX_UNTRACKED_FILES:
        raise RecoveryGitError("untracked fingerprint exceeds file limit")
    digest = hashlib.sha256()
    total = 0
    for raw_name in names:
        try:
            name = raw_name.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RecoveryGitError("untracked path is not valid UTF-8") from exc
        relative = validate_recovery_path(root, name)
        path = root / relative
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise RecoveryGitError("untracked path changed during fingerprint") from exc
        digest.update(relative.encode())
        digest.update(b"\0")
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(b"symlink\0")
            digest.update(os.readlink(path).encode())
        elif stat.S_ISREG(metadata.st_mode):
            if metadata.st_size > MAX_UNTRACKED_FILE_BYTES:
                raise RecoveryGitError("untracked file exceeds fingerprint limit")
            total += metadata.st_size
            if total > MAX_UNTRACKED_TOTAL_BYTES:
                raise RecoveryGitError("untracked fingerprint exceeds byte limit")
            digest.update(b"file\0")
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError as exc:
                raise RecoveryGitError(
                    "untracked path changed during fingerprint"
                ) from exc
        else:
            raise RecoveryGitError("untracked special file cannot be fingerprinted")
        digest.update(b"\0")
    return digest.hexdigest()


def fingerprint_repository(repo: Path) -> RepositoryFingerprint:
    """Hash HEAD plus staged, tracked, and untracked repository content."""

    root = resolve_repo(repo)
    head = _git_bytes(root, ("rev-parse", "HEAD")).decode().strip()
    staged_digest = _sha256(
        _git_bytes(root, ("diff", "--cached", "--binary", "--no-ext-diff"))
    )
    tracked_digest = _sha256(_git_bytes(root, ("diff", "--binary", "--no-ext-diff")))
    untracked_digest = _untracked_digest(root)
    components = {
        "fingerprint_version": 1,
        "head": head,
        "staged_digest": staged_digest,
        "tracked_digest": tracked_digest,
        "untracked_digest": untracked_digest,
    }
    return RepositoryFingerprint(
        fingerprint_version=1,
        state=FingerprintState.available,
        head=head,
        staged_digest=staged_digest,
        tracked_digest=tracked_digest,
        untracked_digest=untracked_digest,
        digest=canonical_digest(components),
    )


def _unavailable_fingerprint() -> RepositoryFingerprint:
    return RepositoryFingerprint(state=FingerprintState.unavailable)


def _fingerprint_or_unavailable(repo: Path) -> RepositoryFingerprint:
    try:
        return fingerprint_repository(repo)
    except (OSError, ValueError, RecoveryGitError, UnsafeRecoveryPathError):
        return _unavailable_fingerprint()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        if os.name == "posix":
            with suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=1)


def _receipt_from_payload(payload: dict[str, object]) -> RecoveryReceipt:
    versioned = {"receipt_version": 1, **payload}
    receipt_id = f"rcp-{canonical_digest(versioned)[:24]}"
    return RecoveryReceipt.model_validate({"receipt_id": receipt_id, **versioned})


def run_verification(
    *,
    repo: Path,
    candidate_id: str,
    brief_digest: str,
    owner_label: str,
    argv: tuple[str, ...],
    timeout_seconds: float,
    completed_at: datetime | None = None,
) -> RecoveryReceipt:
    """Run exactly the owner-supplied argv and retain no process bodies."""

    if not argv or not argv[0]:
        raise ValueError("verification argv must include an executable")
    if timeout_seconds <= 0 or timeout_seconds > 3600:
        raise ValueError("verification timeout must be between 0 and 3600 seconds")
    if (
        not owner_label
        or len(owner_label) > 160
        or any(
            ord(character) < 32 or ord(character) == 127 for character in owner_label
        )
    ):
        raise ValueError("owner label is invalid")

    root = resolve_repo(repo)
    before = _fingerprint_or_unavailable(root)
    resolved_text = shutil.which(argv[0])
    executable = Path(resolved_text).resolve() if resolved_text else None
    executable_name = executable.name if executable is not None else Path(argv[0]).name
    try:
        executable_digest = (
            _file_digest(executable)
            if executable is not None
            else _sha256(b"unavailable")
        )
    except OSError:
        executable = None
        executable_digest = _sha256(b"unavailable")

    started = time.monotonic()
    outcome = VerificationOutcome.error
    exit_code: int | None = None
    process: subprocess.Popen[bytes] | None = None
    if before.available and executable is not None:
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=root,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=(os.name == "posix"),
            )
            try:
                exit_code = process.wait(timeout=timeout_seconds)
                outcome = (
                    VerificationOutcome.exited_zero
                    if exit_code == 0
                    else VerificationOutcome.exited_nonzero
                )
            except subprocess.TimeoutExpired:
                _terminate_process_group(process)
                outcome = VerificationOutcome.timeout
                exit_code = None
        except OSError:
            outcome = VerificationOutcome.error
            exit_code = None
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    after = _fingerprint_or_unavailable(root)
    payload: dict[str, object] = {
        "brief_digest": brief_digest,
        "candidate_id": candidate_id,
        "owner_label": owner_label,
        "executable": executable_name,
        "executable_digest": executable_digest,
        "argv_digest": canonical_digest(list(argv)),
        "argument_count": len(argv) - 1,
        "outcome": outcome,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "repository_before": before,
        "repository_after": after,
        "completed_at": completed_at or datetime.now(UTC),
    }
    return _receipt_from_payload(payload)


def receipt_applicability(
    receipt: RecoveryReceipt | None,
    *,
    candidate_id: str,
    brief_digest: str,
    current: RepositoryFingerprint,
) -> ReceiptApplicability:
    """Compare the latest attempt with current evidence and repository content."""

    if receipt is None:
        return ReceiptApplicability.missing
    if (
        receipt.candidate_id != candidate_id
        or receipt.brief_digest != brief_digest
        or not current.available
        or not receipt.repository_after.available
        or current.digest != receipt.repository_after.digest
    ):
        return ReceiptApplicability.stale
    return ReceiptApplicability.current


class ReceiptStore:
    """Atomic owner-only local receipt persistence."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()

    def _prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def save(self, receipt: RecoveryReceipt) -> Path:
        """Atomically persist one immutable receipt with owner-only permissions."""

        self._prepare()
        target = self.root / f"{receipt.receipt_id}.json"
        descriptor, temporary_name = tempfile.mkstemp(prefix=".receipt-", dir=self.root)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(receipt.model_dump_json())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            os.chmod(target, 0o600)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return target

    def _load(self, path: Path) -> RecoveryReceipt:
        try:
            return RecoveryReceipt.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise ReceiptIntegrityError(
                "stored receipt failed integrity validation"
            ) from exc

    def latest(self, candidate_id: str) -> RecoveryReceipt | None:
        """Return the latest attempt for a candidate, regardless of outcome."""

        if not self.root.is_dir():
            return None
        matches = [
            receipt
            for path in self.root.glob("rcp-*.json")
            if (receipt := self._load(path)).candidate_id == candidate_id
        ]
        return max(
            matches,
            key=lambda item: (item.completed_at, item.receipt_id),
            default=None,
        )
