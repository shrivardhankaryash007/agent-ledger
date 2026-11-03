# Deep adversarial review — agent-ledger (2026-11-03)

- Reviewer: Claude Code (scheduled routine, independent read; no source changes)
- Base commit: `3842ded` (`main`)
- Scope: STATUS, README, `docs/architecture.md`, ADRs 0002–0009, execution packets, `src/`, `tests/`, `scripts/backfill_labels.py`
- Method: every finding below was reproduced with a throwaway script against the real modules (not mocks) unless marked otherwise. Anything not reproduced was dropped.

## TL;DR

1. **The gates are green and the numbers are not trustworthy.** Ruff, format, mypy and pytest all pass (155 tests, 87.36% coverage). Even so, I reproduced four bugs that put wrong numbers into the ledger. **None of them show up as an error.**
   - **Long-prompt pricing is applied to session totals instead of individual calls.** Any session with more than 100k cumulative prompt tokens on a tiered SKU is billed up to 5x.
   - **Replay ignores cache reads.** Cache reads are the largest cost stream, so the "ceiling savings" figure is inflated.
   - **The nightly re-ingest can duplicate spend.** When a worktree is deleted between ingests, the same usage is stored a second time under a new key.
   - **Two attribution states collide on one primary key,** and one row silently overwrites the other.
2. **The attribution failure is mainly a method flaw, not a code bug and not a real negative result** (confidence **75**).
   - **Wrong signal.** Both rescopes changed how the *working directory* gets labelled. Neither changed the signal itself, and the working directory says where the agent process sits, not which repo the work touched.
   - **Wrong metric.** The "98.5%" in ADR 0005 that was used to close the failure measures whether a cwd resolves to *some* git repo. It does not measure whether that repo is the right project. It is also cost-weighted and leaves out rows with no cwd. On ADR 0005's own figures, the full corpus was still about 74% attributed, below the 80% line.
   - **Never measured.** The kill criterion has never been measured by code. Both acceptance tests build a repo at the workspace-root position and count it as an attributed project, so the test cannot fail in the way that matters.
3. **Recommendation: narrow, don't park the substrate.** Freeze the spend/attribution/routing surfaces as "observability only, upper bounds". Run one cheap, pre-registered experiment: attribute workspace-root rows by the repo of the files their tool calls touched. The resume extractor already collects these paths. If that experiment can't reach 80%, park attribution for good. Details and tradeoffs are under [Recommendation](#recommendation).

## Gate output (exact)

Run on Linux, Python 3.11.18, fresh `uv sync` from `uv.lock`.

```
$ uv run ruff check .
All checks passed!            (exit 0)

$ uv run ruff format --check .
65 files already formatted    (exit 0)

$ uv run mypy src
Success: no issues found in 40 source files   (exit 0)

$ uv run pytest
155 passed, 1 warning in 36.85s               (exit 0)
Required test coverage of 80% reached. Total coverage: 87.36%
warning: StarletteDeprecationWarning (fastapi.testclient → httpx2)
```

Coverage on touched/core modules is fine except `ingest/litellm_proxy.py` at **48%** (lines 59–75 `classify`, 141–144 pricing fallback, 184 async path). `recovery/receipts.py` is at 79%, `resume/detector.py` at 79% and `resume/evidence.py` at 76%, all under the per-module 80% rule in AGENTS.md rule 4.

## Ranked findings

Severity reflects impact on the ledger's stated asset (trustworthy spend data). Confidence is my confidence that the defect is real *and* behaves as described, 0–100.

| # | Severity | Conf. | Finding | Location |
|---|---|---|---|---|
| F1 | High | 95 | Long-prompt tier chosen from **bucket sums**, not per call | `ledger/pricing.py:269-271`, `ingest/claude_transcripts.py:347-355` |
| F2 | High | 95 | Replay counterfactual drops cache-read cost → ceiling inflated | `policy/replay.py:99-102` |
| F3 | High | 90 | Nightly re-ingest duplicates spend after a worktree/repo disappears | `ingest/claude_transcripts.py:291`, `ledger/repository.py:45,129` |
| F4 | Medium | 95 | `unknown` and `not_a_repo` buckets share one PK → silent overwrite | `ingest/claude_transcripts.py:210-218,291-293` |
| F5 | Medium | 95 | `doctor` reports "OK" after a failed ingest; one unpriced model blocks every later file | `ledger/heartbeat.py:114`, `ingest/claude_transcripts.py:332-333,373-376` |
| F6 | Medium | 90 | Repo identity wrong for submodules and bare-repo layouts; same-basename repos merge | `ingest/git_label.py:447-455` |
| F7 | Medium | 90 | M0 kill-criterion test is vacuous; the gate metric is not implemented anywhere | `tests/test_m0_ingest_report.py:117-126`, `tests/test_m0_cwd_attribution.py:83-99` |
| F8 | Medium | 85 | `branch` records the branch at *ingest* time, not session time | `ingest/git_label.py:457` |
| F9 | Low-Med | 95 | A transcript with one non-UTF-8 byte is dropped whole, uncounted | `ingest/claude_transcripts.py:129-132` |
| F10 | Low-Med | 90 | `calls_modeled`/`calls_not_modeled` count rows, labelled "calls" | `policy/replay.py:113-118`, `cli.py:279-284` |
| F11 | Low | 90 | `sqlite3.Error` escapes `ingest`'s handler → no failure heartbeat | `cli.py:183-188` |
| F12 | Low | 95 | `except Exception: pass` silently drops sessions from `resume` | `cli.py:352-353`, `cli.py:407-408` |
| F13 | Low | 90 | Owner's OS username / home layout / private project names committed to a public repo | tests fixture dir + docs (see F13) |
| F14 | Low | 90 | Additivity property test avoids the only tiered SKU; STATUS pricing pointer contradicts the table | `tests/test_m0_units.py:137-200`, `STATUS.md` |

<!-- RECOVERY_FINDINGS -->

### F1 — Long-prompt pricing tier is selected from aggregated tokens (High, 95)

`parse_transcript` sums every call in a (session, model, label) bucket, then calls `cost_usd` once with the totals. `cost_usd` picks rates with `_rates_for_prompt(price, in_tokens + cache_read_tokens)` (`pricing.py:269-271`). The tier threshold is a **per-request** property, though, and here it gets compared against a whole-session sum. Once a session's cumulative prompt passes the threshold, *every* call in it is priced at the long rate. With cache reads counted, a normal agent session gets there after a handful of turns.

Repro: 20 separate `claude-haiku-5-5` responses of 10k input each (none near the 100k threshold) → stored `cost_usd=0.1000`, while the sum of the per-call costs is `0.0200`. That is **5.0x** over. The only tiered SKU today is `claude-haiku-5-5`, so current impact is limited to that model. Any future tiered SKU inherits the bug. `test_pricing_tiers.py` tests only single calls, and the additivity property test uses an untiered sonnet SKU (F14), so the suite can't catch this. Fixing it needs per-call cost accumulation inside the bucket. That stays inside `ingest/` and leaves the frozen record shape alone.

### F2 — Replay counterfactual omits cache-read cost (High, 95)

`downgraded_cost` prices only `in_tokens` and `out_tokens` (`replay.py:99-102`). `actual_cost_usd` includes cache reads, and ADR 0006 calls cache reads the dominant stream on this harness. So every cache-read token counts as 100% "savings". Cache writes (inside `in_tokens`) are also re-priced at the plain input rate instead of the write rate.

Repro: one `claude-sonnet-5` record with 1,000,000 cache-read tokens and nothing else → `actual=0.2000, downgraded=0.0000, ceiling_savings=0.2000`. Replay claims the whole bill would be saved by moving to Haiku, which also has a cache-read price. ADR 0009 fixed the not-modeled subtraction but missed this. The $295.12 M2 headline predates v3 cache columns, so it is not affected. **Any replay figure computed since v3 is**, and so is any figure used for FS-2/M2.5 decisions.

### F3 — Re-ingest after a worktree/repo disappears duplicates spend (High, 90)

The row key is `(session_id, model_sku)`, and `session_id` embeds the *resolved label* (`f"{session_id}:{_bucket_tag(label)}{suffix}"`, `claude_transcripts.py:291`). Resolution runs against the filesystem **at ingest time**. The launchd job re-ingests every transcript every night. So when a worktree is removed (routine for agent worktrees), or a repo is moved or deleted, the next ingest resolves the same lines to `not_a_repo` and produces key `S:unknown`. That is a new row. The old `S:<repo>-<worktree>` row is never deleted.

Repro (real `git worktree add` / `remove`): after two ingests, the DB holds `('S1:myrepo-wt-feature','git',1000 tok)` **and** `('S1:unknown','not_a_repo',1000 tok)`. Total cost doubles. This inflates total spend, and it also pushes the measured unattributed share up over time, so it contaminates the attribution measurement itself. Fixing it needs a label-independent row key for transcript rows, or a delete-then-insert per source file. That touches row-key semantics and likely needs an ADR.

### F4 — `unknown` and `not_a_repo` collide on one primary key (Medium, 95)

The bucket key includes `label_source` (`:293`), but `_bucket_tag` returns `"unknown"` for both `unknown` and `not_a_repo` (`:214-215`). One session and model with some lines that have no `cwd` and some lines whose cwd is outside any repo gives two records with the identical `session_id`, and `upsert` overwrites the first with the second.

Repro: lines with `cwd=None` (100 tok) and `cwd=<non-repo dir>` (1000 tok) → `ingest` returns `2`, but the DB holds one row (`not_a_repo`, 1000 tok). 100 tokens are gone, and the returned count is wrong. The same collision happens whenever two distinct buckets map to one tag, for example repo `a-b` versus repo `a` with worktree `b`.

### F5 — `doctor` says "OK" after a failed ingest; one unpriced model blocks the rest of the corpus (Medium, 95)

`is_stale` looks only at `MAX(ts)` of rows (`heartbeat.py:114`) and ignores `last_heartbeat_status`. `parse_transcript` raises `ValueError` for any unpriced model (`:332-333`), and `ingest` stops at that file (`:373-376`). Files sorted before it are written; files after it are never ingested, on every run, until someone edits the pricing table.

Repro: dirs `a/` (priced) and `b/` (model `claude-brand-new-6`) → `ingest` exits 1. `doctor` then prints `Last heartbeat … status=failure`, the error text, and **`OK: ledger is current.`** with exit 0. Any shell or launchd check keyed on `doctor`'s exit code reads this as healthy, and a new model release silently freezes part of the ledger. This is the exact "monitor with no failure signal" problem ADR 0005 §4 set out to remove. The STALE message also says "no successful ingest" while it actually checks row timestamps, which change only when the owner uses Claude Code.

### F6 — Repo identity is wrong for submodules and bare-repo layouts (Medium, 90)

`repo_name = Path(--git-common-dir).parent.name` (`git_label.py:447-448`) assumes the common dir is `<root>/.git`. Reproduced:
- A submodule at `super/vendored-lib` → `repo_name='modules', worktree_name='vendored-lib'`. Every submodule in every repo rolls up to a project called `modules`.
- A bare-repo-plus-worktrees layout (`layout/widget.git` with worktree `layout/main`) → `repo_name='layout'`, the *parent directory* of the bare repo.
- Two different repos that share a basename (`a/api`, `b/api`) → both `api`. ADR 0005 says "never a basename", but repo identity still *is* a basename, just of a different directory.

These come out as confident `label_source='git'` labels, the failure mode ADR 0005 ranks as worse than `unknown`.

### F7 — The attribution gate is never measured; the acceptance tests can't fail on real data (Medium, 90)

The M0 kill criterion is a property of the **real corpus** (call-weighted, ≥80% attributable). Nothing in `src/` computes it: no `report --by label_source`, no attribution-rate command. Every quoted figure (11.6%, 57.8%, 98.5%, ~26%) came from manual analysis that the repo cannot re-run.

`test_m0_ingest_report.py:117-126` asserts the ratio on a synthetic fixture where every cwd was deliberately made into a git repo, so the result is 1.0 by construction. Both attribution tests (`test_m0_ingest_report.py:59`, `test_m0_cwd_attribution.py` hermetic corpus) create a git repo **named `dev` at the workspace-root position** and assert `"dev"` as an attributed project (`test_m0_cwd_attribution.py:98`). The case that killed M0 twice — a session started at the workspace root — is now written into the tests as a pass.

### F8 — `branch` is the branch at ingest time (Medium, 85)

`git rev-parse --abbrev-ref HEAD` runs at ingest time against the current checkout (`git_label.py:457`), and the result is cached per cwd for the whole run. A session from last week on `feature-x` gets the branch that is checked out tonight, and that value is rewritten on every nightly upsert. Because `branch` isn't in the key, it doesn't duplicate rows (unlike F3). Any per-branch analysis is still wrong for every row whose checkout has moved since.

### F9 — One bad byte drops a whole transcript silently (Low-Med, 95)

`iter_transcript_lines` does `read_text(encoding="utf-8")` and returns nothing on `UnicodeDecodeError`/`OSError` (`:129-132`). It doesn't increment `skipped_lines`, and `_usage_lines` doesn't pass `stats` anyway. Repro: two valid usage lines around one line holding a lone `0xFF` byte → `parse_transcript` returns `[]`. A crash-truncated or partially-written transcript, which is exactly what an interrupted session leaves behind, loses all its spend with no signal. Reading bytes and decoding per line with a counted skip would keep the rest.

### F10 — Replay "calls" are rows (Low-Med, 90)

`calls_modeled += 1` per `CallRecord` (`replay.py:113-118`) ignores `record.calls`, and the CLI prints "Modeled: N calls". Repro: one row with `calls=7` → `calls_modeled=1`. The M2 acceptance ("≥500 real calls") and its kill criterion (">50% of calls require guessing") are therefore measured in session-model rows, which are typically one to two orders of magnitude fewer than calls. The 2026-07 "82 unique calls" is presumably 82 rows.

### F11 — SQLite errors bypass the failure heartbeat (Low, 90)

`ingest` catches `(OSError, ValueError, RuntimeError)` (`cli.py:185`). `sqlite3.OperationalError`, for example "database is locked" when a manual ingest overlaps the launchd run, is none of those (verified with `issubclass`). The command crashes with a traceback and writes no failure heartbeat. Mitigation: `doctor` would still eventually go STALE, but only after 72 hours.

### F12 — `resume` swallows every exception per session (Low, 95)

`cli.py:352-353` and `:407-408` wrap per-transcript work in `except Exception: pass`. A detector bug makes sessions disappear from `resume --list` and from the "most recent non-completed" pick with no message. The second case can resume the wrong session.

### F13 — Personal identifiers committed to a public repository (Low, 90)

The repo is public (per the archived STATUS). Tracked content includes the owner's OS username and home-directory layout: the fixture directory name under `tests/fixtures/claude_projects_cwd/`, the fixture's `cwd` values, test source, `scripts/backfill_labels.py`, `STATUS.md`, ADR 0005, the M0 execution packet and the archived status history. Also tracked: a launchd label containing the username, and names of other private projects. These are not credentials, but they are personal content the README says stays local. Stored ledger rows also keep full absolute `cwd_raw` paths. That's fine while the DB stays local, but the column should be stripped before any export or Desk endpoint. No secrets, tokens or API keys were found in tracked files (searched for key/token/secret patterns; matches were variable names only).

### F14 — Test and documentation drift (Low, 90)

- The hypothesis additivity test (`test_m0_units.py:137-200`) uses `_priced_model("sonnet")`, an untiered SKU, so it never exercises the case where additivity fails (F1).
- `STATUS.md` Decisions says "Sonnet 5.5 cache-read corrected to $0.10/MTok". Commit `8e3e084` and `pricing.yaml` (`0.0002`/1k = $0.20/MTok) say the opposite.
- `docs/architecture.md:44-46` still describes `project = path.parent.name` and contains an unfinished sentence ("see ADR 0001... no, see prior-art audit note below").

## Attribution assessment

**Question:** M0's success criterion (≥80% of transcript calls attributable to a project) failed. Was that a code bug, a method flaw, or a genuine negative result?

**Verdict: mainly a method flaw. Code bugs add noise in both directions. It has not been shown to be a genuine negative result. Confidence 75.**

### Working

1. **Each rescope changed the label, not the signal.**
   - The original M0 used the transcript directory, which is the launch cwd: 11.6% attributed.
   - Rescope #1 used the per-line `cwd` basename: 57.8%. The remaining 42.2% is the workspace-root bucket (`EXECUTION-PLAN-m3-resume-packet.md`).
   - ADR 0005 resolves the same per-line `cwd` through git.
   
   All three read **one field**: where the agent's shell was sitting. The original failure, stated in the M0 execution packet, is that most sessions *start at the workspace root and work in a sub-repo*. If the shell never `cd`s, no transformation of `cwd` can recover the sub-repo. That information isn't in the field.

2. **What git resolution does to root-started sessions** (reproduced, `r_root.py`). Take a session whose cwd is the workspace root and which edits a file inside sub-repo `careledger`:
   - root is not a repo → `project='unknown', label_source='not_a_repo'` (honest, but unattributed);
   - root is itself a repo → `project='dev', label_source='git'`. This is counted as resolved, yet it's the same launch-directory label ADR 0005 calls broken, now carrying a git stamp.

3. **The 98.5% figure doesn't measure the criterion.** ADR 0005 computes `git`-labelled cost ÷ (`git` + `not_a_repo`) cost. Compared with the kill criterion it is:
   - cost-weighted instead of call-weighted;
   - restricted to rows that recorded a cwd (`unknown` rows are left out);
   - a measure of whether *a* repo resolves, not of correctness.
   
   On ADR 0005's own numbers, the full-corpus unattributed share was about 26% of cost, roughly 74% attributed and below 80%. The ADR then moved the evaluation to "post-fix data only", and commit `9c8ecf4` deleted the open attribution item from STATUS as "fixed by ADR 0005". The criterion was redefined, never met.

4. **The two possible explanations for 98.5% are both bad news.** Rescope #1 left about 42% of calls at the workspace root, and git resolution can't move a root cwd into a sub-repo (point 2). So a jump to 98.5% resolvable means one of two things:
   - (a) the workspace root is itself a git repo, so root sessions now score as "resolved" under the root's name. Plausible: this workspace keeps versioned workspace-level standards, ADRs and scripts, and both tests model the root as a repo named `dev` (F7). In that case the true per-project attribution is far below 98.5%.
   - (b) the root share really fell from about 42% of calls to about 1.5% of cost, for example because sessions started inside repos after July. That would be a behaviour change, not a fix, and nobody has measured it.
   
   I can't tell which from the repo alone. One query on the owner's machine settles it (see below).

5. **Code bugs contaminate any re-measurement.** F3 adds duplicate `not_a_repo` rows over time and depresses the ratio. F4 deletes some `unknown` rows and inflates it. F6 issues wrong but confident `git` labels and inflates it. F1/F2 distort cost weights. None of these caused the original failure, which happened before git resolution existed. They do mean the current DB can't produce a clean number without a fresh, deduplicated re-ingest into a scratch copy.

6. **Why it isn't a genuine negative result.** A genuine negative would be: "with the best available local signal, under 80% of calls can be tied to a project". The best available signal hasn't been tried. Claude Code transcripts record `tool_use` inputs with absolute `file_path`s, plus Bash invocations. `resume/extractor.py:210-218` and `resume/evidence.py:130-136` already parse them. Resolving those paths to their git repo gives a per-call "repo touched" signal, which is the very thing the kill criterion asks about. Calls that touch nothing, like pure chat or planning turns, could inherit the session's majority repo or stay honestly unattributed.

### Confidence and what would change it

- **75** that the root cause is method (signal plus metric), not code. A code bug alone can't explain the 11.6% → 57.8% history, which predates every bug above.
- The verdict would flip toward **genuine negative** if a touched-files attribution, measured call-weighted on a clean scratch re-ingest, still came in well under 80%. For example, if most root-started cost is in calls that touch no file, or touch files across several repos.
- It would flip toward **already solved** if the owner's check shows the workspace root is *not* a repo and post-fix root-cwd cost really is ~1.5%. Then the remaining gap is just the legacy tail, and ADR 0005's framing is fair apart from the metric mismatch.

**The one-query check** (run locally on a *copy* of the ledger, not in this repo): group v4 rows by `repo_name` and look at the cost share whose `cwd_raw` equals the workspace root. If that share is large and labelled `git`, explanation (a) holds and the 98.5% is mostly root sessions under the root's own name.

## Recommendation

**Narrow, and run one pre-registered attribution experiment before deciding to park.** Don't keep extending the spend/routing surfaces in the meantime.

| Option | What it means | For | Against |
|---|---|---|---|
| **Continue** (treat attribution as fixed, proceed toward M2.5/M4) | Build budgets on `project` | No new work up front | Builds enforcement on an unverified metric. F1–F4 would put wrong numbers into budget decisions. ADR 0002's own gate (80% before M4) isn't met as defined. |
| **Narrow** *(recommended)* | Relabel spend, report and replay as "observability, upper bounds". Fix F1–F5 (all inside `ingest/`, `policy/` and `heartbeat`, and only F3 touches key semantics). Add a codified `attribution-rate` report. Run one experiment: touched-files attribution on a scratch re-ingest, call-weighted, with the 80% threshold and the denominator fixed in advance. | Cheap: the parser for touched files already exists, so the experiment is a few evenings. Gives a real answer to the kill question. Keeps the compounding data asset honest. The recovery surface, which has the observed founder evidence (ADR 0002), is unaffected. | Spends more time on a thesis with no observed founder pain (ADR 0002). The F3 fix needs an ADR. Legacy rows stay unattributable whatever happens. |
| **Park** (stop all spend/attribution work, keep ingest running) | Leave the ledger collecting, freeze reports | Zero effort, and focus goes to recovery | Leaves F1–F5 corrupting the asset every night (F3 grows with every deleted worktree; F5 can silently stop collection). Parking without fixing them parks a slowly degrading dataset. If parking, at least fix F3 and F5. |

Pre-registration for the experiment, so it can't be argued after the fact:
- Population: v4 rows from a clean re-ingest into a scratch DB.
- Unit: API responses (`calls`), not rows.
- Attributed means: the call's `tool_use` file paths resolve to exactly one git repo, or the session's majority repo when the call touches no files. The workspace root never counts as a project.
- Pass: ≥80% call-weighted.
- Fail: <80%. Park attribution permanently and drop the M4 budget wallet.

---
_No source code was changed in this review. Repro scripts were kept outside the repository._
