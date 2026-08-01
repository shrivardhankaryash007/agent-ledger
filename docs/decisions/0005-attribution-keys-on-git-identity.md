# ADR 0005 — Attribution keys on git repo identity, not cwd/launch directory

- Status: **Accepted** (owner-approved 2026-08-02, "agent-ledger export
  spec v2" / "agent-ledger — fix spec")
- Author: Claude (Sonnet 5)

## Context

M0's original attribution key was `path.parent.name` (the Claude Code
transcript directory, itself named from the sanitized cwd at *session
start*), then rescoped once (2026-07-06, see `test_m0_cwd_attribution.py`)
to the per-line `cwd` field's basename. Both were an implicit architectural
choice that was never stated as a decision — nobody decided "attribute by
launch directory," it fell out of using whatever string was cheapest to
read off the transcript.

An export-and-analyze pass on the real ledger (2026-08-02, 257 rows,
$1,361.31, 206 sessions) found that choice had silently broken the product:
86% of spend ($1,171) carried a launch-directory or bare-subdirectory label
(`-Users-yashshrivardhankar-dev`, `frontend`, `api`, `src`, `web`,
`backend`) with no relationship to which repo the work actually touched.
Worktree sessions fragmented under random per-worktree directory names
instead of rolling up to their parent repo. This is exactly the M0 kill
criterion (`docs/architecture.md`: "<80% of transcript calls attributable
to a project") — it fired on 2026-07-06, and the rescope that followed
still used a basename, so it fired again.

Separately, the same analysis found ingestion itself had silently stopped
for 26 days (2026-07-06 -> 2026-08-01, ~$700 of unrecorded spend at the
observed rate) because there was no scheduler at all — `agent-ledger
ingest` was, and had always been, a manual step. A monitoring tool with no
failure signal is worse than no monitoring tool: it converts "I don't know"
into "I think I know."

## Decision

1. **Attribution keys on git repository identity, never on cwd or a
   directory basename.** A session's recorded cwd is resolved via
   `git rev-parse --path-format=absolute --git-common-dir` (parent repo,
   worktree-aware) and `--show-toplevel` (actual checkout, differs from the
   repo root only inside a worktree) and `--abbrev-ref HEAD` (branch). See
   `ingest/git_label.py`.
2. **No silent basename fallback, ever.** When git resolution fails —
   deleted worktree, not a repo, permission error, or the recorded cwd
   itself is empty — the row is honestly `label_source='not_a_repo'` (or
   `'unknown'` when there was no cwd to try) with `repo_name=None`. An
   honest NULL is worth more than a confident wrong label; it shows up in a
   report as "unattributed," which is true.
3. **Additive schema, no data loss.** `CallRecord`/`call_records` gained
   `repo_name`, `worktree_name`, `branch`, `cwd_raw`, `label_source`
   (MODEL_VERSION/SCHEMA_VERSION 1 -> 2, `repository.migrate()` does an
   in-place `ALTER TABLE` on existing databases). `project` stays the
   always-populated grouping key existing reports rely on (`repo_name` when
   resolved, else `"unknown"`) — no downstream consumer of `.project` had
   to change.
4. **Collection failure must be loud.** `collector_heartbeat` records one
   row per `agent-ledger ingest` invocation, success or failure
   (`ledger/heartbeat.py`). `agent-ledger doctor` reports newest-row age,
   last heartbeat, and 7-day volume, and exits non-zero when the newest row
   is older than 72h.
5. **The instrument runs on its own now.** A launchd agent
   (`~/Library/LaunchAgents/com.yashshrivardhankar.agent-ledger.ingest.plist`)
   runs `agent-ledger ingest ~/.claude/projects` daily. This is the actual
   fix for "collection stopped" — `doctor` only makes the *next* gap
   visible, it doesn't prevent one.
6. **Legacy rows are reconciled, not guessed.** The one-off backfill
   (`scripts/backfill_labels.py`) deletes pre-fix rows whose source
   transcript still exists (proven redundant: two consecutive real
   `ingest` runs after this fix were idempotent, so a still-existing
   source has already been correctly reprocessed into a v2 row) and
   relabels the rest — whose source is gone and whose historical
   tokens/cost must never be touched — via path-decode and
   `git worktree list` matching only. Never by timestamp-correlating to
   commits; with 8+ repos active in overlapping windows that would invent
   attribution instead of recovering it. `project` is updated alongside
   the new columns for these rows too (`repo_name` when resolved, else
   `"unknown"`) — an earlier version of `update_labels()` left `project`
   at its pre-fix value, which meant `report`/`replay` kept grouping
   backfilled rows under the exact broken labels this fix removes; caught
   by spot-checking `agent-ledger report` after the first backfill run,
   not by any test (see Consequences).
7. **The rule is the artifact, not just this collector's code.** The next
   collector — Codex, Antigravity, whatever comes next — inherits "resolve
   cwd to git identity, fail honest" from this ADR, not by re-deriving the
   same bug independently.

## Consequences

- Going forward, any row where a cwd was actually recorded resolves via
  git 98.5% of the time (measured on the real corpus post-fix,
  `git`-labeled cost / (`git` + `not_a_repo`)-labeled cost). The remaining
  1.5% is genuinely deleted/moved repos, not a resolution bug.
- The real ledger's overall unattributed share only fell to ~26% of total
  cost, not below the fix spec's 10% target — but that residual is
  entirely `model_version=1` legacy rows whose source transcript no longer
  exists on disk (unrecoverable by construction, not a defect in the new
  resolution path). Re-measuring on post-fix data only is the meaningful
  number for judging this ADR; re-measuring on the full historical corpus
  will asymptotically improve as the legacy tail ages out of any rolling
  window, but never reaches 0% for data whose source is permanently gone.
- `report/spend.py` and `policy/replay.py` needed no changes — both key
  off `CallRecord.project`, which kept its contract.
- M1 (`ingest/litellm_proxy.py`) is unaffected: its records intentionally
  carry `repo_name`/`worktree_name`/`branch`/`label_source=None` forever
  (no cwd concept; it attributes via an explicit `caller_tag` instead).
  `label_source=None` there means "this source doesn't attempt git
  resolution," distinct from `'unknown'` ("attempted, no cwd available").
- A session run from inside a worktree now costs three extra `git`
  subprocess calls per distinct cwd; `parse_transcript`'s `git_cache`
  parameter (shared across an entire `ingest()` run) keeps this from
  scaling with line count, only with distinct-cwd count.
- Adding a fourth attribution signal (e.g. a Codex-native session marker)
  is additive under this same contract — extend `GitLabel`/`label_source`,
  do not reintroduce a basename fallback as a shortcut.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Keep `Path(cwd).name`, just document the gap | Already tried twice (M0 original, 2026-07-06 rescope); both failed the same kill criterion the same way. Documenting a broken mechanism isn't a fix. |
| Backfill legacy rows by timestamp-correlating to git commits | Explicitly rejected by the fix spec: with 8+ repos active in overlapping windows this invents attribution rather than recovering it. |
| Silent basename fallback when git resolution fails | This is the exact failure mode being removed — a confident wrong label is worse than an honest `unknown`, because it hides in `per_project()` sums looking like real data. |
| Cron instead of launchd | No precedent in this workspace; every other scheduled workspace process (cockpit, cosmos, vault-context-mcp) already uses launchd — one scheduling mechanism, not two. |
| Delete all `model_version=1` rows uniformly (simpler script) | Would have silently discarded ~46 sessions' worth of irreplaceable spend history whose source transcripts are gone — verified by checking file existence per session before any deletion, not assumed. |

## Verification

Real-corpus verification (2026-08-02): schema migration applied in place to
the production `data/ledger.db` (387 rows post-migration, no data loss vs.
the pre-fix 257-row/$1,361.31 snapshot until the backfill's *proven*
duplicate removal). Two consecutive real `agent-ledger ingest` runs against
`~/.claude/projects` were idempotent (identical row counts/totals modulo
one concurrently-running session), establishing that the full reprocessable
corpus had already been captured before any row was deleted. The backfill
dry-run was reviewed before being applied for real; a pre-backfill database
snapshot (`data/ledger.db.pre-backfill-2026-08-02.bak`) was kept as a
rollback path. `agent-ledger doctor` correctly reports `OK: ledger is
current` immediately after a real ingest and `STALE`/exit 1 on an empty
database. Full gate (ruff format/check, mypy --strict, pytest) passes; see
`STATUS.md` for the exact numbers.
