"""One-off backfill for the pre-2026-08-02 rows (fix spec v2, Backfill
section). Not part of the product surface — run once, by hand.

Every row with ``model_version = 1`` predates the git-aware attribution fix;
no current code path writes that version anymore, so this is the exact and
only set of legacy rows. For each one:

1. If its source transcript (``<session_id-before-first-':'>.jsonl``) still
   exists under the Claude Code projects dir, the full corpus reprocess
   already recomputed it correctly as one or more v2 rows (see
   ``docs/decisions/0005-attribution-keys-on-git-identity.md`` for the
   verification: two consecutive real `ingest` runs were idempotent, and
   every reprocessable session's data reappears under a v2 row). The old
   row is then a stale duplicate — deleting it is what stops it inflating
   `per_project()`/`replay` totals, not a courtesy.
2. If the source transcript is gone, the row is the only surviving copy of
   that historical spend (AGENTS.md rule 1: it must survive every
   iteration). Its tokens/cost/session_id are never touched — only
   ``repo_name``/``worktree_name``/``branch``/``label_source`` are
   backfilled, best-effort, from two heuristics:
   a. Decode a path-encoded ``project`` (``-Users-x-y`` -> ``/Users/x/y``)
      and resolve it via git, if that path is still a repo today.
   b. Match a worktree-shaped ``project`` against `git worktree list`
      across every known repo under ~/dev, if that worktree still exists.
   Anything neither resolves is left honestly ``label_source='unknown'``
   (never guessed by timestamp-matching commits — see the fix spec).

Usage:
    uv run python scripts/backfill_labels.py [--db-path PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_ledger.ingest.git_label import resolve
from agent_ledger.ledger.repository import delete_by_session_ids, update_labels

DEFAULT_DB_PATH = Path("data/ledger.db")
DEFAULT_PROJECTS_DIR = Path("~/.claude/projects").expanduser()
KNOWN_REPO_ROOTS = (Path("~/dev").expanduser(), Path("~/00_base").expanduser())


@dataclass(frozen=True)
class LegacyRow:
    session_id: str
    model_sku: str
    project: str


def _base_session_id(session_id: str) -> str:
    return session_id.split(":", 1)[0]


def _existing_transcript_stems(projects_dir: Path) -> set[str]:
    if not projects_dir.is_dir():
        return set()
    return {p.stem for p in projects_dir.rglob("*.jsonl")}


def _known_repo_dirs() -> list[Path]:
    """Every directory under the known roots that is itself a git repo."""

    repos: list[Path] = []
    for root in KNOWN_REPO_ROOTS:
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir() and (child / ".git").exists():
                repos.append(child)
    return repos


def _worktree_paths(repo: Path) -> list[Path]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    paths = []
    for line in completed.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.removeprefix("worktree ")))
    return paths


def _decode_path_encoded(project: str) -> Path | None:
    """``-Users-yashshrivardhankar-dev`` -> ``/Users/yashshrivardhankar/dev``,
    the naive reversal (works when no path component itself contains '-')."""

    if not project.startswith("-"):
        return None
    candidate = Path("/" + project.lstrip("-").replace("-", "/"))
    return candidate if candidate.is_dir() else None


def _resolve_legacy_project(
    project: str, worktree_index: dict[str, Path]
) -> Path | None:
    """Best-effort reversal of a legacy ``project`` string to a real path.

    Tries, in order: naive path-encoded decode, then an exact worktree
    directory-name match against every currently-existing worktree of every
    known repo. Returns None (honest 'unknown') if neither resolves.
    """

    decoded = _decode_path_encoded(project)
    if decoded is not None:
        return decoded
    worktree_match = worktree_index.get(project)
    if worktree_match is not None:
        return worktree_match
    # A path-encoded worktree suffix, e.g.
    # "-Users-x-dev--claude-worktrees-brave-faraday-77aa0e".
    for name, path in worktree_index.items():
        if project.endswith(name):
            return path
    return None


def run(db_path: Path, projects_dir: Path, *, dry_run: bool) -> None:
    existing_stems = _existing_transcript_stems(projects_dir)
    worktree_index = {
        path.name: path for repo in _known_repo_dirs() for path in _worktree_paths(repo)
    }

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        legacy_rows = [
            LegacyRow(row["session_id"], row["model_sku"], row["project"])
            for row in connection.execute(
                "SELECT session_id, model_sku, project FROM call_records "
                "WHERE model_version = 1"
            )
        ]

    to_delete: list[str] = []
    to_backfill: list[LegacyRow] = []
    for row in legacy_rows:
        if _base_session_id(row.session_id) in existing_stems:
            to_delete.append(row.session_id)
        else:
            to_backfill.append(row)

    resolved_count = 0
    unknown_count = 0
    print(f"Legacy (model_version=1) rows: {len(legacy_rows)}")
    print(f"  -> superseded by a reprocessed v2 row, deleting: {len(to_delete)}")
    print(f"  -> irreplaceable (source gone), backfilling labels: {len(to_backfill)}")

    if not dry_run and to_delete:
        deleted = delete_by_session_ids(db_path, to_delete)
        print(f"Deleted {deleted} superseded row(s).")
    elif to_delete:
        print(f"[dry-run] Would delete {len(to_delete)} superseded row(s).")

    for row in to_backfill:
        target = _resolve_legacy_project(row.project, worktree_index)
        if target is None:
            resolved_count_delta = 0
            unknown_count += 1
            label = resolve(None)  # label_source='unknown', everything else None
        else:
            label = resolve(str(target))
            resolved_count_delta = 1 if label.label_source == "git" else 0
        resolved_count += resolved_count_delta

        if not dry_run:
            update_labels(
                db_path,
                session_id=row.session_id,
                model_sku=row.model_sku,
                repo_name=label.repo_name,
                worktree_name=label.worktree_name,
                branch=label.branch,
                label_source=label.label_source,
            )

    print(f"  -> resolved via git: {resolved_count}")
    print(f"  -> left honestly unknown: {unknown_count}")
    if dry_run:
        print("[dry-run] No changes written. Re-run with --apply to write them.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=DEFAULT_PROJECTS_DIR,
        help="Claude Code transcripts dir (default: ~/.claude/projects)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without writing anything.",
    )
    args = parser.parse_args()
    run(args.db_path, args.projects_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
