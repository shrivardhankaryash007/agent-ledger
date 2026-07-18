"""Lazy, digest-checked access to repository-bound recovery sessions."""

from __future__ import annotations

import hashlib
from threading import Lock
from typing import TYPE_CHECKING

from agent_ledger.recovery.assembler import recover_evidence
from agent_ledger.recovery.git_state import resolve_repo
from agent_ledger.recovery.models import SessionCatalog

if TYPE_CHECKING:
    from pathlib import Path

    from agent_ledger.recovery.adapters.base import (
        RecoveryAdapter,
        TranscriptEvidence,
    )
    from agent_ledger.recovery.discovery import DiscoveredSession, DiscoveryResult
    from agent_ledger.recovery.models import RecoveryBrief


class UnknownCandidateError(LookupError):
    """Raised when an opaque candidate ID is not in the startup catalog."""


class SessionSourceChangedError(RuntimeError):
    """Raised when a transcript no longer matches its discovery-time digest."""


def _source_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RecoveryCatalog:
    """Immutable startup catalog with lazy, stable transcript extraction."""

    def __init__(
        self,
        *,
        repo: Path,
        discovery: DiscoveryResult,
        adapters: tuple[RecoveryAdapter, ...],
    ) -> None:
        """Bind discovered private locators to declared provider adapters."""

        self._repo = resolve_repo(repo)
        self._discovered = {
            item.candidate.candidate_id: item for item in discovery.sessions
        }
        self._catalog = SessionCatalog(
            repo_name=self._repo.name,
            sessions=tuple(item.candidate for item in discovery.sessions),
            excluded_count=discovery.excluded_count,
        )
        self._adapters = {
            (adapter.source_adapter.name, adapter.source_adapter.version): adapter
            for adapter in adapters
        }
        self._cache: dict[str, TranscriptEvidence] = {}
        self._cache_lock = Lock()
        missing_adapters = {
            (
                item.candidate.source_adapter.name,
                item.candidate.source_adapter.version,
            )
            for item in discovery.sessions
        } - self._adapters.keys()
        if missing_adapters:
            raise ValueError("discovered session has no declared adapter")

    @property
    def public(self) -> SessionCatalog:
        """Return the privacy-redacted immutable startup catalog."""

        return self._catalog

    def _selected(self, candidate_id: str) -> DiscoveredSession:
        try:
            return self._discovered[candidate_id]
        except KeyError as exc:
            raise UnknownCandidateError(candidate_id) from exc

    def _extract_stable(self, candidate_id: str) -> TranscriptEvidence:
        selected = self._selected(candidate_id)
        try:
            before = _source_digest(selected.source_path)
        except OSError as exc:
            raise SessionSourceChangedError from exc
        if before != selected.source_digest:
            raise SessionSourceChangedError

        with self._cache_lock:
            cached = self._cache.get(candidate_id)
            if cached is not None:
                return cached
            identity = selected.candidate.source_adapter
            adapter = self._adapters[(identity.name, identity.version)]
            try:
                evidence = adapter.extract(selected.source_path)
                after = _source_digest(selected.source_path)
            except (OSError, ValueError) as exc:
                raise SessionSourceChangedError from exc
            if after != selected.source_digest:
                raise SessionSourceChangedError
            self._cache[candidate_id] = evidence
            return evidence

    def recover(self, candidate_id: str) -> RecoveryBrief:
        """Assemble fresh Git truth from stable, memoized transcript evidence."""

        return recover_evidence(self._extract_stable(candidate_id), self._repo)
