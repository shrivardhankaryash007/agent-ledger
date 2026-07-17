"""Repository-bound, privacy-redacted recovery session discovery."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agent_ledger.recovery.git_state import RecoveryGitError, resolve_repo
from agent_ledger.recovery.models import SessionCandidate

if TYPE_CHECKING:
    from agent_ledger.recovery.adapters.base import RecoveryAdapter


@dataclass(frozen=True)
class AdapterRoot:
    """One configured provider adapter and its local transcript root."""

    adapter: RecoveryAdapter
    root: Path


@dataclass(frozen=True)
class DiscoveredSession:
    """Public candidate paired with its private local source locator."""

    candidate: SessionCandidate
    source_path: Path
    source_digest: str


@dataclass(frozen=True)
class DiscoveryResult:
    """Bound sessions and an aggregate count of excluded candidates."""

    sessions: tuple[DiscoveredSession, ...]
    excluded_count: int


def _candidate_id(provider: str, source_session_id: str) -> str:
    payload = f"{provider}\0{source_session_id}".encode()
    return f"ses-{hashlib.sha256(payload).hexdigest()[:20]}"


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_bound_to_repo(recorded_cwd: str | None, trusted_root: Path) -> bool:
    if recorded_cwd is None or "\\" in recorded_cwd:
        return False
    raw = Path(recorded_cwd).expanduser()
    if not raw.is_absolute():
        return False
    try:
        resolved = raw.resolve(strict=True)
        resolved.relative_to(trusted_root)
        return resolve_repo(resolved) == trusted_root
    except (OSError, ValueError, RecoveryGitError):
        return False


def discover_sessions(
    *,
    repo: Path,
    roots: tuple[AdapterRoot, ...],
    limit: int = 20,
    scan_limit: int = 60,
) -> DiscoveryResult:
    """Discover newest repository-bound sessions without exposing source paths."""

    if limit < 1 or scan_limit < limit:
        raise ValueError("discovery limits must be positive and scan >= result")
    trusted_root = resolve_repo(repo)
    excluded = 0
    by_id: dict[str, DiscoveredSession] = {}
    for configured in roots:
        available = configured.adapter.iter_sources(configured.root)
        available_with_mtime: list[tuple[float, Path]] = []
        for path in available:
            try:
                available_with_mtime.append((path.stat().st_mtime, path))
            except OSError:
                excluded += 1
        ranked = [
            path for _, path in sorted(available_with_mtime, reverse=True)[:scan_limit]
        ]
        for source_path in ranked:
            try:
                inspected = configured.adapter.inspect(source_path)
            except (OSError, ValueError):
                excluded += 1
                continue
            if not _is_bound_to_repo(inspected.recorded_cwd, trusted_root):
                excluded += 1
                continue
            candidate_id = _candidate_id(
                inspected.provider,
                inspected.source_session_id,
            )
            try:
                source_digest = _file_digest(source_path)
            except OSError:
                excluded += 1
                continue
            discovered = DiscoveredSession(
                candidate=SessionCandidate(
                    candidate_id=candidate_id,
                    provider=inspected.provider,
                    source_adapter=inspected.source_adapter,
                    source_session_id=inspected.source_session_id,
                    project_hint=inspected.project_hint,
                    started_at=inspected.started_at,
                    updated_at=inspected.updated_at,
                    ending=inspected.ending,
                    unmatched_call_count=inspected.unmatched_call_count,
                ),
                source_path=source_path,
                source_digest=source_digest,
            )
            existing = by_id.get(candidate_id)
            if (
                existing is None
                or discovered.candidate.updated_at > existing.candidate.updated_at
            ):
                by_id[candidate_id] = discovered

    ordered = sorted(
        by_id.values(),
        key=lambda item: (item.candidate.updated_at, item.candidate.candidate_id),
        reverse=True,
    )
    return DiscoveryResult(sessions=tuple(ordered[:limit]), excluded_count=excluded)
