"""Git-aware label resolution: resolves a recorded cwd to a stable repo
identity, worktree-aware. Fix spec 2026-08-02 — replaces the old
``Path(cwd).name`` fallback, which is what silently mislabeled 86% of
historical spend under the launch directory instead of the repo actually
worked in (see docs/decisions/0005-attribution-keys-on-git-identity.md).

Deliberately never falls back to a cwd/path basename: an honest
``label_source='not_a_repo'`` is worth more than a confident wrong label.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_ledger.ledger.models import LabelSource

_GIT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class GitLabel:
    """Resolved attribution for one cwd, or the honest absence of one."""

    repo_name: str | None
    worktree_name: str | None
    branch: str | None
    label_source: LabelSource


_UNKNOWN = GitLabel(
    repo_name=None, worktree_name=None, branch=None, label_source="unknown"
)
_NOT_A_REPO = GitLabel(
    repo_name=None, worktree_name=None, branch=None, label_source="not_a_repo"
)


def resolve(cwd: str | None) -> GitLabel:
    """Resolve one recorded cwd to a repo identity.

    Args:
        cwd: The working directory recorded for a session/line, or ``None``/
            empty if the source never captured one.

    Returns:
        A ``GitLabel``. ``label_source`` is ``'unknown'`` only when ``cwd``
        itself is missing; any cwd git rejects (deleted worktree, not a
        repo, permission error) is ``'not_a_repo'`` with ``repo_name`` left
        ``None`` — never a guessed basename. Inside a worktree, ``repo_name``
        is the *parent* repo (via ``--git-common-dir``) and ``worktree_name``
        holds the worktree's own directory name; outside a worktree,
        ``worktree_name`` is ``None``.

    Example:
        >>> resolve(None).label_source
        'unknown'
        >>> resolve("/does/not/exist").label_source
        'not_a_repo'
    """

    if not cwd:
        return _UNKNOWN

    common_dir = _git(cwd, ("rev-parse", "--path-format=absolute", "--git-common-dir"))
    if common_dir is None:
        return _NOT_A_REPO

    repo_root = Path(common_dir).parent
    repo_name = repo_root.name

    worktree_name: str | None = None
    work_root_raw = _git(cwd, ("rev-parse", "--show-toplevel"))
    if work_root_raw is not None:
        work_root = Path(work_root_raw)
        if work_root != repo_root:
            worktree_name = work_root.name

    branch = _git(cwd, ("rev-parse", "--abbrev-ref", "HEAD"))

    return GitLabel(
        repo_name=repo_name,
        worktree_name=worktree_name,
        branch=branch,
        label_source="git",
    )


def _git(cwd: str, arguments: tuple[str, ...]) -> str | None:
    """Run one read-only git command against ``cwd``; ``None`` on any failure."""

    try:
        completed = subprocess.run(
            ["git", "-C", cwd, *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = completed.stdout.strip()
    return output or None
