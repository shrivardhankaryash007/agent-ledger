"""Unit tests for ingest.git_label.resolve — the fix spec 2026-08-02
snippet (--git-common-dir/--show-toplevel/--abbrev-ref HEAD) against real
temporary git repos, including a real worktree."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_ledger.ingest.git_label import resolve


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q"], cwd=path)
    _run(["git", "checkout", "-q", "-b", "main"], cwd=path)
    _run(
        [
            "git",
            "-c",
            "user.email=test@test",
            "-c",
            "user.name=Test",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=path,
    )


def test_resolve_repo_root_returns_git_label_source(tmp_path: Path) -> None:
    repo = tmp_path / "myrepo"
    _init_repo(repo)

    label = resolve(str(repo))

    assert label.label_source == "git"
    assert label.repo_name == "myrepo"
    assert label.worktree_name is None
    assert label.branch == "main"


def test_resolve_worktree_rolls_up_to_parent_repo_name(tmp_path: Path) -> None:
    repo = tmp_path / "parentrepo"
    _init_repo(repo)
    worktree = tmp_path / "parentrepo-wt-feature"
    _run(
        ["git", "worktree", "add", "-q", "-b", "feature", str(worktree)],
        cwd=repo,
    )

    label = resolve(str(worktree))

    assert label.label_source == "git"
    # This is the subtlety the fix spec calls out: repo_name must be the
    # *parent* repo, not the worktree's own directory.
    assert label.repo_name == "parentrepo"
    assert label.worktree_name == "parentrepo-wt-feature"
    assert label.branch == "feature"


def test_resolve_non_repo_path_is_not_a_repo_not_a_guessed_basename(
    tmp_path: Path,
) -> None:
    not_a_repo = tmp_path / "just_a_folder"
    not_a_repo.mkdir()

    label = resolve(str(not_a_repo))

    assert label.label_source == "not_a_repo"
    assert label.repo_name is None
    assert label.worktree_name is None
    assert label.branch is None


def test_resolve_missing_path_is_not_a_repo(tmp_path: Path) -> None:
    label = resolve(str(tmp_path / "does_not_exist"))

    assert label.label_source == "not_a_repo"
    assert label.repo_name is None


def test_resolve_no_cwd_is_unknown() -> None:
    assert resolve(None).label_source == "unknown"
    assert resolve("").label_source == "unknown"
