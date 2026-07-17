"""Read-only, path-safe Git snapshotting for session recovery."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class RecoveryGitError(RuntimeError):
    """Raised when the trusted repository cannot be inspected."""


class UnsafeRecoveryPathError(ValueError):
    """Raised when transcript-provided path data escapes the trusted repository."""


@dataclass(frozen=True)
class PathState:
    """Current state of one validated repository-relative path."""

    path: str
    exists: bool
    differs_from_head: bool
    porcelain_status: str


@dataclass(frozen=True)
class GitSnapshot:
    """Read-only Git facts observed at recovery time."""

    root: Path
    repo_name: str
    branch: str
    head: str
    worktree_clean: bool
    path_states: tuple[PathState, ...]


def _git(root: Path, arguments: tuple[str, ...]) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryGitError("trusted repository could not be inspected") from exc
    return completed.stdout.strip()


def resolve_repo(repo: Path) -> Path:
    """Resolve an owner-selected path to its containing Git repository.

    Args:
        repo: Explicit repository path or invocation working directory.

    Returns:
        Canonical Git worktree root.

    Raises:
        RecoveryGitError: If the path is missing, not a directory, or not in Git.
    """

    try:
        candidate = repo.expanduser().resolve(strict=True)
    except OSError as exc:
        raise RecoveryGitError("trusted repository path does not exist") from exc
    if not candidate.is_dir():
        raise RecoveryGitError("trusted repository path is not a directory")
    root_text = _git(candidate, ("rev-parse", "--show-toplevel"))
    root = Path(root_text).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RecoveryGitError("Git returned a root outside the trusted path") from exc
    return root


def validate_recovery_path(root: Path, recorded_path: str) -> str:
    """Normalize a transcript path and prove it remains inside ``root``.

    Args:
        root: Canonical trusted repository root.
        recorded_path: Untrusted path from a tool invocation.

    Returns:
        Normalized POSIX repository-relative path. A contained absolute input is
        converted only after canonical containment is proven.

    Raises:
        UnsafeRecoveryPathError: If the path is ambiguous or escapes.
    """

    if not recorded_path or "\\" in recorded_path:
        raise UnsafeRecoveryPathError("recorded path is empty or non-POSIX")
    pure = PurePosixPath(recorded_path)
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise UnsafeRecoveryPathError("recorded path is ambiguous or traverses")
    candidate = (
        Path(recorded_path).resolve(strict=False)
        if pure.is_absolute()
        else (root / Path(*pure.parts)).resolve(strict=False)
    )
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeRecoveryPathError(
            "recorded path escapes the trusted repository"
        ) from exc
    if not relative.parts or relative.parts[0].startswith("-"):
        raise UnsafeRecoveryPathError("recorded path may not resemble a Git option")
    return relative.as_posix()


def inspect_git(repo: Path, recorded_paths: tuple[str, ...]) -> GitSnapshot:
    """Capture current Git state using only fixed read-only commands.

    Args:
        repo: Explicit trusted repository path.
        recorded_paths: Untrusted paths extracted from transcript tool calls.

    Returns:
        Current repository and per-path state.

    Raises:
        RecoveryGitError: If Git inspection fails.
        UnsafeRecoveryPathError: If any recorded path is unsafe.
    """

    root = resolve_repo(repo)
    normalized_paths = tuple(
        dict.fromkeys(validate_recovery_path(root, item) for item in recorded_paths)
    )
    branch = _git(root, ("rev-parse", "--abbrev-ref", "HEAD"))
    head = _git(root, ("rev-parse", "HEAD"))
    full_status = _git(root, ("status", "--porcelain=v1", "--untracked-files=all"))
    states: list[PathState] = []
    for relative_path in normalized_paths:
        status = _git(
            root,
            (
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                relative_path,
            ),
        )
        states.append(
            PathState(
                path=relative_path,
                exists=(root / relative_path).exists(),
                differs_from_head=bool(status),
                porcelain_status=status[:2] if status else "",
            )
        )
    return GitSnapshot(
        root=root,
        repo_name=root.name,
        branch=branch,
        head=head,
        worktree_clean=not bool(full_status),
        path_states=tuple(states),
    )
