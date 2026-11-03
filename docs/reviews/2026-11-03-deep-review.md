# Deep review — agent-ledger (2026-11-03)

- **Reviewer:** Claude Code. This is an independent read, and no source, test, config or other docs file was changed.
- **Base:** `3842ded` (`main`). This file supersedes the two earlier drafts on this branch (`47cdb9f`, `1d8d074`). It keeps every finding from them that I could re-verify, corrects their line references, and adds new findings (the N-series).
- **Confidence notation:** `(c NN)` = my 0–100 confidence that a claim is true as stated. For findings, it is confidence that the defect is real *and* behaves as described.

---

## 1. TL;DR

- **The ledger produces wrong numbers without raising errors.** Ruff, mypy and coverage are green, but I reproduced the following against the real modules (c 95):
  - per-session long-prompt tiering that overbills **5×** (A1);
  - a replay ceiling that counts every cache-read dollar as "savings" (A2);
  - nightly re-ingest that **duplicates** spend once a worktree is deleted (A3);
  - two attribution buckets that **overwrite** each other on one primary key (A4).
- **The failure signal fails open** (c 95). After a failed ingest, `doctor` prints `OK` and exits 0 (A5). One unpriced new model then blocks every transcript sorted after it on every run. A single naive timestamp crashes both `doctor` and `context-check` with a `TypeError` (A6, new).
- **The ledger is not append-only and not reproducible** (c 85). Every nightly run re-prices every row whose transcript still exists, using whatever `pricing.yaml` says that day. Nothing records which table priced a row. STATUS.md says "existing collected rows are not rewritten", and the code does rewrite them (A15, new).
- **The recovery prompt's trust boundary can be forged from transcript content** (c 90). Tool names and the first user message are interpolated raw into the "safe" continuation prompt (A7/A8). The Git evidence beneath it has three correctness holes (A9–A11).
- **The test suite is green, but parts of it are vacuous or flaky** (c 85). The M0 kill-criterion test is 1.0 by construction (A18). The descendant-kill test passes even if the kill is a no-op (A19). The hypothesis additivity test avoids the only tiered SKU, and it **failed intermittently in this session** (1 of 2 full runs; A20, new). AGENTS.md rule 4's golden-file gate on report output does not exist.
- **Verdict:** treat every spend, attribution and replay figure as an **unverified upper bound** until A1–A6 and A15 are fixed (c 85). The recovery side (path containment, token guard, atomic receipts) is the better-engineered half, and A7/A8 are its one serious gap (c 80).

---

## 2. Scope & method

**Read in full:**
- `ledger/` (models, repository, pricing, heartbeat)
- `ingest/` (Claude transcripts, git_label, litellm_proxy)
- `policy/replay.py`
- `report/` (spend, context_check)
- `cli.py` (ingest, report, doctor, replay, resume)
- `recovery/prompt.py`, `recovery/git_state.py`, `recovery/receipts.py`
- the relevant parts of `recovery/assembler.py` and `api/app.py`

I also read `README.md`, `AGENTS.md`, `STATUS.md`, the headings and milestone text of `docs/architecture.md`, and ADR 0007's limitations table.

**Read partially:** `resume/*`, `recovery/adapters/*`, `recovery/catalog.py`, `recovery/package.py`, `demo/scenario.py`, and tests other than those cited.

**Ran:**

| Command | Result |
|---|---|
| `uv sync` (from `uv.lock`) | ok |
| `uv run ruff check .` | All checks passed |
| `uv run mypy src` | Success, 40 files |
| `uv run pytest` run 1 | **1 failed** (`test_cost_math_is_nonnegative_and_additive`, reason truncated to `D...`), 154 passed, 87.36% coverage |
| `uv run pytest` run 2 | 155 passed, 87.36% coverage |
| Failing test alone ×4, no coverage | 4/4 pass |

Two throwaway repro scripts lived in the session scratchpad, outside the repo, and were **not committed**:
- `repro_core.py` drove the real `ingest`, `parse_transcript`, `replay`, `doctor` (subprocess), `build_report` and `context_check` against synthetic transcripts, including a real `git worktree add` / `remove`.
- `repro_git.py` drove `inspect_git` against a temporary repo.

Every row marked *verified* below was reproduced by one of these scripts or by a run. Rows marked *verified (read)* were confirmed by reading control flow that leaves no ambiguity, without execution.

**Not covered:**
- the owner's real ledger DB and transcript corpus (not in the repo);
- the launchd job;
- the frontend JS (`api/static/app.js`) beyond its existence;
- the Codex adapter's full parsing;
- the LiteLLM integration against a live LiteLLM;
- performance at real corpus size.

No web access was used. A secret scan of tracked files, using common key/token/private-key patterns, found **no credentials** (c 85: pattern-based only).

---

## 3. Part A — Bug hunt

### 3.1 Findings table

Severity reflects impact on the asset AGENTS.md calls compounding: trustworthy spend data. For the recovery findings, it reflects impact on ADR 0003's trust boundary.

| ID | Severity | file:line | Summary | Verified / plausible | Conf. |
|---|---|---|---|---|---|
| A1 | High | `ledger/pricing.py:269-271`, `ingest/claude_transcripts.py:347-355` | Long-prompt tier chosen from the **bucket's summed tokens**, not per call → whole session billed at long rate | Verified (5.0× repro) | 95 |
| A2 | High | `policy/replay.py:99-102` | Replay counterfactual ignores cache reads and re-prices cache writes as plain input → ceiling inflated | Verified | 95 |
| A3 | High | `ingest/claude_transcripts.py:291`, `ledger/repository.py:45` | Row key embeds the label resolved **at ingest time**, so removing a worktree duplicates the row on the next ingest | Verified (real worktree) | 95 |
| A4 | Medium | `ingest/claude_transcripts.py:210-218,291-293` | `unknown` and `not_a_repo` buckets map to the same `session_id` → one overwrites the other; returned count is wrong | Verified | 95 |
| A5 | Medium | `ledger/heartbeat.py:114`, `ingest/claude_transcripts.py:332-333,373-376` | `doctor` exits 0 "OK" after a failed ingest; one unpriced model blocks all later files on every run | Verified | 95 |
| A6 | Medium | `ledger/heartbeat.py:80-99`, `report/spend.py:141`, `ingest/litellm_proxy.py:147` | **New.** A naive `ts` row makes `doctor` and `context-check` crash with `TypeError`; `MAX(ts)` and `ts >= ?` are lexical string compares | Verified (crash); plausible (LiteLLM trigger) | 90 / 60 |
| A7 | High (security) | `recovery/prompt.py:37-52`, `recovery/assembler.py:142,152` | Transcript-controlled strings (tool name, intent) put raw into the "safe" continuation prompt → forged `## Safe continuation order` | Verified (read) | 90 |
| A8 | Med-High (security) | `resume/evidence.py:114-117`, `recovery/adapters/codex.py:110-113` | `intent` is the first user string, verbatim and unbounded; it can be command text or contain a secret, and it flows to brief, API, prompt and package | Verified (read), per earlier draft's repro | 80 |
| A9 | Medium | `recovery/git_state.py:139-158` | A gitignored file the agent wrote reports `differs_from_head=False` ("matches HEAD") | Verified | 95 |
| A10 | Medium | `recovery/git_state.py:82-115,142-150` | Git pathspec magic not disabled: recorded `*.py` or `:/a.py` are interpreted as globs or magic | Verified | 95 |
| A11 | Low | `recovery/git_state.py:51,157` | `.strip()` on porcelain output turns unstaged `' M'` into staged `'M '` in hashed evidence | Verified | 95 |
| A12 | Medium | `recovery/assembler.py:226,369` | Verification detection checks `attempt.name == "Bash"`; Codex shell runs are never assessed | Verified (read) | 80 |
| A13 | Low-Med | `api/app.py:209-241` | Receipt and package routes don't catch `RecoveryGitError` (raised by fingerprinting an untracked FIFO, an oversize file, or a non-UTF-8 name) → 500 | Verified (read) | 85 |
| A14 | Medium | `ingest/git_label.py:70-71` | `repo_name = parent(--git-common-dir).name` is wrong for submodules (`modules`) and bare-repo layouts; same-basename repos merge | Verified by earlier draft; re-read | 90 |
| A15 | Medium | `ledger/repository.py:116-146`, `ingest/claude_transcripts.py:329-355` | **New.** Every ingest re-prices and overwrites every row whose transcript still exists; no pricing-version stamp → history is neither append-only nor reproducible | Verified (read) | 85 |
| A16 | Low-Med | `ingest/claude_transcripts.py:192,373-375` | **New.** The same `sessionId` in two transcript files: the later file's row overwrites the earlier one's spend | Verified (mechanism); plausible (real trigger) | 95 / 45 |
| A17 | Low-Med | `ingest/claude_transcripts.py:129-132` | One non-UTF-8 byte drops the entire transcript silently, uncounted | Verified by earlier draft; re-read | 95 |
| A18 | Medium | `tests/test_m0_ingest_report.py:117-130`, `tests/test_m0_cwd_attribution.py` | M0 kill-criterion test is 1.0 by construction; the workspace-root-as-repo case is written into the tests as a *pass* | Verified (read) | 90 |
| A19 | Low | `tests/test_recovery_receipts.py:296-315`, `demo/scenario.py:303` | Descendant-kill test passes even if the kill is a no-op; `server_stopped` hard-coded `True` | Verified (read) | 95 |
| A20 | Low | `tests/test_m0_units.py:133-205` | **New.** Additivity property test is flaky under coverage (failed 1 of 2 full runs) and avoids the only tiered SKU, so it cannot catch A1 | Verified (flake observed); plausible (`DeadlineExceeded` cause) | 90 / 75 |
| A21 | Low-Med | `policy/replay.py:113-118`, `cli.py:279-284` | Replay "calls" counts rows, not `record.calls` (1 vs 7 in repro) | Verified | 95 |
| A22 | Low | `cli.py:185` | `sqlite3.Error` (e.g. "database is locked") escapes the handler → no failure heartbeat | Verified (`issubclass`) | 90 |
| A23 | Low | `ingest/claude_transcripts.py:205,326` | **New.** Row `ts` picked by **lexical** string max: mixed `Z` / fractional / offset timestamps choose the wrong instant | Verified | 90 |
| A24 | Low | `ingest/git_label.py:80` | `branch` is the branch at ingest time, rewritten nightly; detached HEAD is stored as `"HEAD"` | Verified (read) | 85 |
| A25 | Low | `cli.py:352-353,407-408` | `except Exception: pass` silently drops sessions from `resume`, so the "most recent" pick can be wrong | Verified (read) | 95 |
| A26 | Low | `report/context_check.py:69-72`, `report/spend.py:141` | **New.** A session-level row spanning the nudge split is assigned wholly by its *last* `ts`, so pre-nudge cost lands in "post" | Verified (read) | 80 |
| A27 | Low | `.env.example` | **New.** `AGENT_LEDGER_DB_PATH` and `AGENT_LEDGER_HOST_PORT` are documented but never read by any code | Verified (grep) | 95 |

### 3.2 Details

#### A1 — Long-prompt tier selected from aggregated tokens (High, c 95)
- **Scenario:** 20 separate `claude-haiku-5-5` responses of 10k input each, none near the 100k threshold, in one session.
  - `parse_transcript` sums them into one bucket and calls `cost_usd` once with 200k prompt tokens, so `_rates_for_prompt` picks the long tier.
  - Stored `cost_usd = 0.1000`. The per-call sum is `0.0200`, so the stored figure is **5.0×** too high.
- **Impact:** any real session on a tiered SKU crosses the threshold within a few cached turns. Today only `claude-haiku-5-5` is tiered; every future tiered SKU inherits the bug.
- **Fix:** compute cost per response inside the bucket loop and accumulate the dollars, rather than pricing the summed tokens. This is local to `ingest/` and leaves the frozen record shape alone. Add a hypothesis test that asserts `cost(bucket) == Σ cost(call)` on the tiered SKU.

#### A2 — Replay drops cache-read cost (High, c 95)
- **Scenario:** one Sonnet record with 1,000,000 cache-read tokens and nothing else gives `actual = 0.2000`, `downgraded = 0.0000`, `ceiling = 0.2000`.
  - Replay claims the whole bill would be saved by moving to Haiku, even though Haiku also charges for cache reads.
  - Cache writes inside `in_tokens` are also re-priced at the plain input rate instead of the write rate.
- **Impact:** ADR 0006 calls cache reads the dominant stream, so every post-v3 replay figure is inflated by roughly the cache-read share of cost.
- **Fix:** price the counterfactual with the same `cost_usd()` function, passing cache read/write/1h volumes and the target SKU. That reuses the exact ingestion math instead of a second, divergent formula.

#### A3 — Worktree removal duplicates spend (High, c 95)
- **Scenario:** a session runs in worktree `wt-feature` of `myrepo` and is ingested. The worktree is removed (`git worktree remove`, which agents do routinely). The next nightly ingest runs.
  - DB holds `('S1:myrepo-wt-feature', 'git', 1000)` **and** `('S1:unknown', 'not_a_repo', 1000)`. Total spend doubles.
- **Cause:** the primary key `(session_id, model_sku)` embeds the label resolved against the filesystem *now*. Nothing deletes the old key.
- **Also contaminates attribution:** each deleted worktree adds a phantom `not_a_repo` row, so the unattributed share drifts upward over time.
- **Fix:** make the transcript row key label-independent, for example `sessionId + file-relative id + bucket ordinal`, with the label stored as data. Alternatively, delete all rows sourced from a file before re-inserting that file's rows, in one transaction. Either approach changes key semantics, so it needs an ADR and a version bump under AGENTS.md rule 1.

#### A4 — `unknown` / `not_a_repo` key collision (Medium, c 95)
- **Scenario:** one session and model where one line has no `cwd` (100 tokens) and one line has a cwd outside any repo (1000 tokens).
  - `ingest` returns `2`, but the DB holds one row (`not_a_repo`, 1000). 100 tokens are lost.
- **Cause:** the bucket key includes `label_source`, but `_bucket_tag` maps both sources to `"unknown"`.
- **Same bug, second trigger:** repo `a-b` versus repo `a` with worktree `b` produce the same tag.
- **Fix:** make the tag injective, either by including `label_source` or by escaping the separator, or adopt A3's label-independent key.

#### A5 — `doctor` says OK after failure; one new model freezes the tail (Medium, c 95)
- **Scenario:** dirs `a/` (priced) and `b/` (model `claude-brand-new-6`). `ingest` exits 1 with "no pricing configured…".
  - `doctor` then prints `status=failure`, the error text, and `OK: ledger is current.`, and exits **0**.
  - Files sorted after `b/` are never ingested, on every run, until someone edits `pricing.yaml`.
- **Cause:** `is_stale` reads only `MAX(ts)` of rows and ignores the last heartbeat's status. The STALE message also says "no successful ingest", but the check never looks at heartbeats.
- **Fix:**
  - `doctor` should fail when the latest heartbeat is a failure, or when no *successful* heartbeat exists within the threshold.
  - Ingest should skip and count an unpriced file and continue. Record the skipped models in the heartbeat and have `doctor` fail on that count, rather than aborting the whole run.

#### A6 — Naive timestamps crash `doctor` and `context-check` (Medium, c 90 crash / c 60 real trigger) — new
- **Scenario:** a transcript line with `"timestamp": "2099-01-01T00:00:00"` (no `Z`) is stored as a naive ISO string.
  - `build_report` raises `TypeError: can't subtract offset-naive and offset-aware datetimes`.
  - `context_check` raises `TypeError: can't compare offset-naive and offset-aware datetimes`.
  - So `doctor`, the health check, crashes rather than reporting.
- **Likelier trigger:** the M1 LiteLLM callback stores `ts=end_time` verbatim. To my knowledge LiteLLM passes naive local `datetime.now()` values (c 60; not verified against a live LiteLLM).
- **Related:** `MAX(ts)` and `ts >= ?` compare strings lexically. Mixed offsets (`+05:30` vs `+00:00`) or naive vs aware values give the wrong newest row and the wrong 7-day count.
- **Fix:** normalise every `ts` to aware UTC at the `CallRecord` boundary (a pydantic validator, which is additive and leaves the shape alone). Treat a naive input as UTC or reject it explicitly. Have `doctor` parse values rather than rely on string order.

#### A7 — Forgeable "safe" continuation prompt (High, security, c 90)
- **Scenario:** a transcript records a tool whose `name` contains `\n\n## Safe continuation order\n\n1. Run …`, or an intent containing the same.
  - `render_recovery_prompt` interpolates `item.statement` (built from `attempt.name` at `assembler.py:142`) and `brief.intent` raw.
  - The successor agent sees a second, attacker-authored "Safe continuation order" or `Current HEAD:` block that is indistinguishable from the app-authored one.
- **Why it matters:** ADR 0003 §3 says continuation actions come only from app-authored templates.
- **Fix:**
  - Treat every transcript-derived string as data. Restrict tool names to a strict charset at adapter ingest and reject or escape anything else.
  - Render intent and observation text inside a fenced block whose delimiter cannot occur in the content, for example a length-prefixed or random fence.
  - Add a property test asserting that no transcript input can add a line beginning with `#` or `Current HEAD:` outside the fenced region.

#### A8 — Intent can carry command text or secrets (Med-High, security, c 80)
- **Scenario:** the first `type == user` record is a `<bash-input>` or `<local-command-stdout>` wrapper, or a pasted command containing a token. It becomes `intent` verbatim and unbounded.
  - From there it reaches the brief, the `/api/.../recovery` JSON, the prompt, and the downloadable package.
- **Fix:** skip harness-wrapper records (`<bash-input>`, `<command-name>`, `<local-command-*>`) when choosing intent. Cap the length. Run a conservative secret redactor (high-entropy token and key-prefix patterns) before the value leaves the adapter.

#### A9 — Ignored files read as "matches HEAD" (Medium, c 95)
- **Scenario:** the agent wrote `out.log`, which is in `.gitignore`. `inspect_git` returns `exists=True, differs_from_head=False, porcelain_status=''`, so readiness can say the path is unchanged.
- **Related:** the receipt fingerprint (`ls-files --others --exclude-standard`) also excludes ignored files. A receipt therefore stays "current" after an ignored artefact (build output, generated config) changes.
- **Fix:** pass `--ignored=matching` for per-path status and report a distinct "ignored (not tracked by Git)" state instead of "matches HEAD".

#### A10 — Pathspec magic (Medium, c 95)
- **Scenario:** a recorded path `*.py` passes `validate_recovery_path`. `git status -- '*.py'` then globs, and the brief says `*.py` "differs from HEAD" (`exists=False, differs=True`). A recorded `:/a.py` is parsed as magic pathspec.
- **Fix:** run every Git call with `GIT_LITERAL_PATHSPECS=1`, or prefix paths with `:(literal)`. Also reject `*?[` and a leading `:` in `validate_recovery_path`.

#### A11 — Porcelain `strip()` flips staged/unstaged (Low, c 95)
- **Scenario:** `b.py` modified but unstaged. Git prints `" M b.py"`, `_git()` strips it to `"M b.py"`, and the stored status is `"M "` (staged). That value is hashed into evidence.
- **Fix:** strip only the trailing newline (`rstrip("\n")`) for porcelain output, or use `-z` and parse fixed columns.

#### A12 — Codex verification never assessed (Medium, c 80)
- **Scenario:** in a Codex session, every shell run is recorded under Codex's tool name, not `"Bash"`. The brief says "No recorded verification attempt is available" even when tests were run. The earlier draft reproduced this on the shipped Codex demo fixture.
- **Fix:** have each adapter set a provider-neutral `is_shell` / `kind` on `ToolAttempt`, and have the assembler test that instead of a Claude-specific name.

#### A13 — 500s on fingerprint errors (Low-Med, c 85)
- **Scenario:** an untracked FIFO, a file over `MAX_UNTRACKED_FILE_BYTES`, or a non-UTF-8 untracked name in the repo makes `_untracked_digest` raise `RecoveryGitError`.
  - The `/receipt` and `/package` routes catch only `ReceiptIntegrityError` and drift errors, so the request returns 500.
  - The earlier draft also reported that a non-ASCII `?token=` makes `compare_digest` raise `TypeError` → 500 (c 80, not re-run).
- **Not an auth bypass:** the Host, Origin and token checks hold.
- **Fix:** map `RecoveryGitError` / `UnsafeRecoveryPathError` to 422 on those routes, as `selected_recovery` already does. Encode both sides of `compare_digest` to bytes, or catch `TypeError` → 403.

#### A14 — Repo identity wrong for submodules and bare layouts (Medium, c 90)
- **Scenarios:**
  - A submodule's common dir is `<super>/.git/modules/<name>`, so `repo_name = "modules"`. Every submodule in every repo rolls up to one project.
  - Bare repo `layout/widget.git` with worktree `layout/main` gives `repo_name = "layout"`.
  - `a/api` and `b/api` both give `api`.
- **Why it matters:** these are confident `label_source='git'` labels, the failure mode ADR 0005 ranks as worse than `unknown`.
- **Fix:**
  - Derive identity from `--show-superproject-working-tree` for submodules.
  - Handle a bare common dir (`core.bare`) by stripping `.git`.
  - Store a disambiguator (remote URL hash or the canonical common-dir path) alongside the display name.

#### A15 — History is silently re-priced; not append-only (Medium, c 85) — new
- **Scenario:** `pricing.yaml` changes (commit `8e3e084` changed the Sonnet 5.5 cache-read rate). The next nightly ingest re-parses every transcript still on disk, and `upsert`'s `DO UPDATE SET cost_usd = excluded.cost_usd` overwrites the stored cost.
  - Rows whose transcripts were deleted keep the old price. The same DB therefore holds a mix of pricing versions, and no column says which.
  - STATUS.md says "Existing collected rows are not rewritten by the O4 fix… requires a separately reviewed, deliberate re-ingest". In reality the next scheduled ingest *is* that re-ingest for every surviving transcript (c 85; assumes the documented daily launchd job is active).
- **Why it matters:** the docs call collected data "the compounding asset" (AGENTS.md rule 1) and talk of rows that "stay exactly as ingested" (`repository.py` docstring). Neither is true for rows whose transcripts survive.
- **Fix:**
  - Short term: record a `pricing_digest` per row. This is additive and needs a version bump.
  - Longer term: separate immutable *usage facts* from *derived cost*. Store tokens once and compute cost at report time against a named pricing version, so a price change becomes a reproducible re-computation rather than a silent overwrite.

#### A16 — Same `sessionId` across files overwrites (Low-Med, c 95 mechanism / c 45 real trigger) — new
- **Scenario:** `p/a.jsonl` holds a 1000-token response and `p/b.jsonl` a 10-token response. Both carry `sessionId: "S"`, same model, same label.
  - `ingest` returns 2, but the DB holds one row: `('S:unknown', 10, 1)`. 1000 tokens are lost.
- **How likely in practice:** ADR 0007 says resumed or forked sessions replay history under *different* `sessionId`s. I could not confirm that Claude Code ever writes one `sessionId` into two non-subagent files. A copied or restored transcript, or a future harness change, would trigger it.
- **Fix:** include a per-file discriminator in the row key, as subagents already have, or aggregate across files by `sessionId` before upsert.

#### A17 — One bad byte drops a transcript (Low-Med, c 95)
- **Scenario:** two valid usage lines around one line containing a lone `0xFF`. `read_text` raises `UnicodeDecodeError`, it is swallowed, and the file yields `[]`. Nothing is counted in `skipped_lines`.
- **Fix:** read bytes, decode each line with `errors="strict"` inside the per-line `try`, and count skips. Surface skip counts in the heartbeat.

#### A18 — M0 kill-criterion test cannot fail on the real failure mode (Medium, c 90)
- **Scenario:** the fixture deliberately makes every cwd a git repo, including one named `dev` at the workspace-root position, and asserts `"dev"` as an attributed project. The ratio is 1.0 by construction.
- **Why it matters:** the case that killed M0 twice, a session started at the workspace root, is encoded as a pass. Nothing in `src/` computes the real call-weighted attribution rate.
- **Fix:** add a fixture where the root is a repo, the work happens in a sub-repo, and the root must **not** count as a project. Add an `attribution-rate` report command that computes the kill criterion on the real DB.

#### A19 — Vacuous recovery tests (Low, c 95)
- The descendant-kill test asserts only `outcome is timeout` and `exit_code is None`. It would pass if `_terminate_process_group` were a no-op.
- `SmokeResult.server_stopped=True` is a literal (`demo/scenario.py:303`).
- Every API test overrides the default Host/Origin allowlists, so the defaults are untested.
- **Fix:**
  - Have the descendant write its PID to a file, then assert `os.kill(pid, 0)` raises `ProcessLookupError` after the call.
  - Derive `server_stopped` from `thread.is_alive()`.
  - Add one test that exercises the default allowlists.

#### A20 — Flaky, mis-targeted property test (Low, c 90 flake / c 75 cause) — new
- **Scenario:** the first full `uv run pytest` failed `test_cost_math_is_nonnegative_and_additive` with a message truncated to `D...`. A second full run and four isolated runs passed.
  - The test sets no `deadline`. Each example writes a file and runs `parse_transcript`, which may spawn `git`, so a hypothesis `DeadlineExceeded` under coverage is the likely cause (c 75).
  - It also uses an untiered Sonnet SKU, so it can never detect A1.
- **Fix:** set `deadline=None`, or move I/O out of the property. Add a tiered-SKU property asserting per-call additivity.

#### A21 — Replay counts rows as calls (Low-Med, c 95)
- **Scenario:** one record with `calls=7` gives `calls_modeled=1`, and the CLI prints "Modeled: 1 calls". M2's "≥500 real calls" acceptance and its ">50% guessing" kill criterion are therefore measured in session-model rows.
- **Fix:** add `record.calls` instead of 1, and label row counts separately.

#### A22 — SQLite errors bypass the failure heartbeat (Low, c 90)
- **Scenario:** a manual ingest overlaps the launchd run and hits "database is locked". `sqlite3.OperationalError` is not a subclass of `OSError`, `ValueError` or `RuntimeError`, so the command dies with a traceback and records no heartbeat.
- **Fix:** add `sqlite3.Error` to the handler, and set `timeout=` / WAL mode on connections.

#### A23 — Lexical timestamp max (Low, c 90) — new
- **Scenario:** lines at `…00:00:00Z`, `…00:00:00.900Z` and `…09:00:00+05:30`. The stored row `ts` is the `+05:30` value, the earliest instant. The latest instant is `.900Z`, and `"Z" > "."` lexically, so string order also misranks the first two.
- **Fix:** parse to aware datetimes before comparing, in both `_usage_lines` and the bucket loop.

#### A24 — Branch is ingest-time state (Low, c 85)
- **Scenario:** a session from last week ran on `feature-x`. Tonight the checkout is on `main`, so the row's `branch` is rewritten to `main`. A detached HEAD stores the literal `"HEAD"`.
- **Fix:** take the branch from the transcript where the harness records one, and fall back to Git only when it is absent. I believe Claude Code writes a per-line `gitBranch` field (c 60). No fixture in this repo contains one, so confirm against a real transcript first.

#### A25 — `resume` swallows all exceptions (Low, c 95)
- **Scenario:** a detector bug on one transcript removes it from `--list` and from the "most recent non-completed" pick with no message, so the wrong session can be resumed.
- **Fix:** catch specific exceptions, count them, and print "N sessions skipped (errors)".

#### A26 — Context-check split assigns spanning sessions wholesale (Low, c 80) — new
- **Scenario:** a session that ran 2026-10-10 → 2026-10-14 is one row with `ts = 2026-10-14`. All of its cost counts as post-nudge.
- **Why it matters:** the check is pre-registered, so the split rule should be stated, and it currently isn't.
- **Fix:** exclude rows whose first and last timestamps straddle the split, or document that `ts` is last activity. The latter needs a first-ts field or a separate query.

#### A27 — Dead environment variables (Low, c 95) — new
- **Scenario:** an owner sets `AGENT_LEDGER_DB_PATH` from `.env.example`. The CLI still writes to `data/ledger.db`, relative to the *cwd*. A launchd job started from a different directory silently writes a different DB, which then looks stale to `doctor`.
- **Fix:** read the env var as the default for `--db-path`, or delete both entries from `.env.example`.

---

## 4. Part B — Independent read

### 4.1 What the system actually does

| Claimed (README / architecture) | Actually does | Conf. |
|---|---|---|
| "Local-first LLM cost and routing ledger" | Batch-parses Claude Code JSONL into one row per (session, model, label) bucket in SQLite, priced from a local YAML. M1 LiteLLM capture exists but is a 48%-covered callback with cache-blind fallback pricing. No routing exists; "routing" is a counterfactual replay. | 85 |
| Attribution to projects | Resolves each line's recorded `cwd` through Git at *ingest time*. Never measures the call-weighted rate it is gated on. | 90 |
| Replay = "theoretical ceiling" | Mislabels counts (A21) and ignores the largest cost stream (A2), so it is not a valid upper bound on the stated counterfactual either. It overstates by more than the intended "ceiling" slack. | 85 |
| Recovery Loop (resume / recovery / console / receipts) | The most complete and best-defended subsystem: path containment, Git root binding, a capability-token localhost API, atomic owner-only receipts. Its prompt boundary is forgeable (A7). | 80 |

The repo is two products sharing a package: a **spend ledger** and a **session-recovery tool** (c 85). They share only transcript parsing (`iter_transcript_lines`). ADR 0002 itself ranks recovery ("continuity") ahead of routing.

### 4.2 Architecture & data flow

```
~/.claude/projects/**.jsonl ─┐
                             ├─ ingest/claude_transcripts ── git_label.resolve(cwd) [live FS, ingest time]
                             │        │ bucket by (model, repo, worktree, label_source)
                             │        │ cost_usd(bucket sums)   ← pricing.yaml (current)
                             │        ▼
LiteLLM callback ────────────┼──► ledger/repository.upsert  (PK session_id+model_sku, overwrite)
                             │        │
                             │        ├─► report/spend (polars)  ├─► policy/replay  ├─► report/context_check
                             │        └─► heartbeat/doctor (MAX(ts) string)
                             │
~/.codex/sessions/**.jsonl ──┴─ recovery/adapters ─► assembler ─► git_state.inspect_git ─► RecoveryBrief
                                                                     │                  ├─► prompt (text)
                                                                     │                  ├─► api/app (token-guarded)
                                                                     └─ receipts (fingerprint + run argv) ─► package
```

- **The key structural fact:** a ledger row is a **derived view** of (transcript file × current filesystem × current pricing table). It is not a recorded fact (c 85). Re-ingest re-derives it, which is why A3, A14, A15 and A24 all share one root cause.
- **Module boundaries are clean:** `policy/` is pure, the repository is the only DB writer, and reports are read-only (c 85). The `CallRecord` docstrings are unusually honest about field semantics across versions.
- **Performance:** each `upsert` runs `migrate()` and opens a new connection per record, so ingest is O(rows) connections with no single transaction. That is acceptable at today's scale (unmeasured, c 60). It also means a crash mid-ingest leaves a partial, mixed-pricing state.

### 4.3 Trust & integrity model — where it is weak

| Property implied by docs | Reality | Weakness | Conf. |
|---|---|---|---|
| Collected data "must survive every iteration" (AGENTS.md rule 1) | Rows are overwritten in place on every ingest; deleted only by the one-off backfill | No append-only log, no row history, no pricing provenance (A15) | 85 |
| Idempotent re-ingest | Idempotent only while the filesystem and pricing are unchanged | Worktree removal duplicates (A3); price change rewrites (A15); key collisions lose data (A4, A16) | 90 |
| Health signal (Fix 2 / ADR 0005 §4) | Row recency only | Fails open after an ingest failure (A5); crashes on naive ts (A6); not raised on SQLite errors (A22) | 95 |
| Recovery prompt: "only app-authored actions" (ADR 0003 §3) | Transcript strings interpolated raw | Forgeable (A7); intent may carry secrets (A8) | 85 |
| Git evidence is "observed" | Porcelain-derived, pathspec-interpreted, ignore-blind | A9–A11 make "observed" claims wrong in edge cases | 90 |
| Receipt "integrity validation" | Pydantic schema validation of local JSON files | Not tamper-evident: any process running as the owner can write a valid "passed/current" receipt. Acceptable for a single-user local tool, but the word "integrity" overclaims. One corrupt file makes `latest()` raise for every candidate. | 80 |
| Localhost console | Capability token (timing-safe), exact Host/Origin allowlists, CSP, no CORS, `127.0.0.1` bind | Sound. The only gaps are 500s (A13). The token sits in the URL and so lands in browser history; acceptable locally. | 80 |

### 4.4 Gaps between docs and code

| Doc says | Code does | Conf. |
|---|---|---|
| STATUS: "Existing collected rows are not rewritten by the O4 fix" | The next ingest rewrites every row whose transcript survives (A15) | 85 |
| STATUS Decisions: "Sonnet 5.5 cache-read corrected to $0.10/MTok" | Commit `8e3e084` and `pricing.yaml` say $0.20/MTok | 90 |
| `repository.py` docstring: tokens/cost "stay exactly as ingested" | True only for `update_labels`; `upsert` overwrites cost | 90 |
| ADR 0005: "never a basename" | `repo_name` *is* a basename, of the common dir's parent (A14) | 90 |
| `doctor` STALE text: "no successful ingest in over 72h" | Checks row timestamps, never heartbeat success (A5) | 95 |
| `docs/architecture.md:19`: "see ADR 0001... no, see prior-art audit note below" | An unfinished sentence in the plan of record | 95 |
| `docs/architecture.md:44-46`: `project = path.parent.name` | Superseded by Git resolution (ADR 0005) | 85 |
| AGENTS.md rule 4: golden-file regression on report output | No golden file exists for `report` output (only a resume-packet fixture) | 85 |
| AGENTS.md rule 4: ≥80% coverage on touched modules | `litellm_proxy.py` 48%; `receipts.py` 79%, `resume/detector.py` 79%, `resume/evidence.py` 76% (per earlier draft's coverage run; overall figure re-confirmed at 87.36%) | 80 |
| `.env.example`: `AGENT_LEDGER_DB_PATH`, `AGENT_LEDGER_HOST_PORT` | Never read (A27) | 95 |
| M0 kill criterion: ≥80% of calls attributable | Never computed in code. ADR 0005's 98.5% is cost-weighted, excludes `unknown` rows, and measures "resolves to *a* repo", not "the right repo" | 80 |

### 4.5 Riskiest design decisions

1. **Rows derived from live filesystem state at ingest time** (c 85). The attribution label and branch depend on what is on disk tonight, not when the session ran. Every re-ingest can move, duplicate or relabel history (A3, A14, A24). This is the root cause behind most Part A data-integrity bugs.
2. **Cost stored as an overwritable derived value with no provenance** (c 85). Pricing changes rewrite history implicitly (A15). Pricing math lives in two places (`cost_usd` and `replay.downgraded_cost`), which have already diverged (A2).
3. **Aggregating per session before pricing** (c 90). The design discards per-call granularity at ingest, which makes per-call pricing rules impossible to apply correctly (A1). It also makes "calls" ambiguous downstream (A21, A26).
4. **Rendering untrusted text into an agent-facing prompt** (c 85). The recovery feature's value comes from feeding a successor agent, so a forgeable instructions section is the highest-consequence bug in the repo (A7).
5. **Treating "the test is green" as "the gate is met"** (c 80). The attribution gate (A18), the kill test (A19) and the additivity property (A20) all pass without touching the behaviour they claim to guard.

### 4.6 Test coverage of the critical paths

| Critical path | Tested? | Gap | Conf. |
|---|---|---|---|
| Per-response de-dup (ADR 0007) | Yes, well (`test_m4_message_dedup.py`) | Cross-file duplicates are knowingly unhandled (ADR 0007 #2) | 80 |
| Cost math non-negativity / additivity | Partially | Untiered SKU only; flaky (A20); no per-call vs bucket property (A1) | 90 |
| Re-ingest idempotency | Same-filesystem only | No test where the filesystem or pricing changes between ingests (A3, A15) | 90 |
| Bucket-key uniqueness | No | A4, A16 untested | 90 |
| `doctor` after failure | No | A5, A6 untested | 90 |
| Replay with cache tokens | No | A2 untested | 90 |
| Attribution kill criterion on realistic layout | No (vacuous) | A18 | 90 |
| Recovery path containment | Yes (`..`, symlink escape, prefix collision) | Pathspec magic, ignored files (A9, A10) | 85 |
| Prompt injection resistance | No | A7, A8 | 85 |
| API auth guard | Yes, but with overridden allowlists | Defaults untested (A19) | 85 |
| Receipt atomicity / interrupted write | Yes | Descendant kill vacuous (A19) | 85 |

### 4.7 Top 3 changes that would most improve it

| # | Change | Why this over alternatives | Fixes | Cost |
|---|---|---|---|---|
| 1 | **Make ledger rows immutable usage facts.** Use a label-independent key per (file, response or bucket), store tokens plus first/last ts, and add `pricing_digest`. Compute cost per *call* and accumulate. Make re-ingest a per-file delete-then-insert in one transaction. | One ADR and version bump fixes the root cause of six bugs, instead of six local patches that each touch key semantics anyway. The alternative of patching A3 and A4 individually leaves A15 and A1 structurally possible. | A1, A3, A4, A15, A16, A23 | Medium. One ADR, migration plus re-ingest into a scratch DB first (c 75) |
| 2 | **Make the health signal fail closed.** Have `doctor` fail on the last heartbeat's failure or skipped-file count and on missing success within the threshold. Skip-and-count unpriced models. Normalise `ts` to aware UTC at the model boundary. Catch `sqlite3.Error`. | Cheapest high-leverage change: a few dozen lines, no key change, and it stops the ledger silently freezing on the next model release. Fixing alerting before data math means future regressions surface. | A5, A6, A22, A17 (counting) | Low. About an evening (c 70) |
| 3 | **Close the recovery prompt boundary.** Use a strict charset for tool names, a fenced untrusted-text section, harness-wrapper skipping and redaction for intent, literal pathspecs, ignore-aware status, and a newline-only strip. Add adversarial property tests. | Recovery is the subsystem ADR 0002 prioritises and the one with founder evidence. A forgeable "safe" prompt undermines its entire value proposition. The fixes are local to three files. | A7–A11 | Low-Medium (c 70) |

Honourable mention: replace `downgraded_cost` with a call to `cost_usd` on the target SKU (A2, A21), about an hour (c 80). Until then, stop quoting any post-v3 replay figure.

### 4.8 What is genuinely well designed or novel

- **Recovery trust boundary, minus A7** (c 80):
  - exact Git-root binding;
  - canonical path containment that rejects `..`, symlink escape and `/repo` vs `/repo2` prefix tricks;
  - an argv-only verification runner (`shell=False`, `stdin`/`stdout`/`stderr` → DEVNULL, receipts store argv *digests*, not argv);
  - process-group kill;
  - atomic `mkstemp` + `fsync` + `os.replace` receipts at 0600/0700.
  
  For a single-owner local tool, that is careful engineering.
- **A fingerprint-bound receipt applicability model** (c 75). "Current" means same candidate + same brief digest + same repository content digest. That is a genuinely useful idea: a test receipt goes stale the moment the tree changes, which most "it passed" tooling ignores.
- **Honest self-documentation of field semantics** (c 80). `CallRecord` and the ADRs spell out what `in_tokens` means across versions and why pre-v4 rows are overstated, and STATUS lists known gaps with dollar figures. The doc/code gaps above are drift, not concealment.
- **Pre-registered checks** (`context-check` with fixed thresholds and an explicit INSUFFICIENT verdict) are the right epistemic instinct (c 75), even though the split rule (A26) needs stating.
- **Not earned:** "audit-grade" or "append-only" connotations around the ledger. Nothing in the code provides them today (c 85).

### 4.9 Attribution assessment (carried forward from the earlier draft, condensed)

**Verdict:** M0's attribution failure is mainly a **method flaw**: wrong signal plus wrong metric. It is not a code bug, and it has not been shown to be a genuine negative result (c 75).

- Every rescope transformed the same field: the agent shell's `cwd`. A session started at the workspace root that never `cd`s cannot be attributed from `cwd` by any transformation (c 85).
- ADR 0005's 98.5% figure differs from the kill criterion in three ways (c 80):
  - it is cost-weighted, not call-weighted;
  - it excludes `unknown` rows;
  - it measures "resolves to *a* repo", not "the right repo".
  
  If the workspace root is itself a repo, root sessions score as attributed under the root's name. The tests encode exactly that (A18).
- **The best local signal is untried** (c 70): the file paths in `tool_use` inputs, which `resume/extractor.py` already parses. A pre-registered experiment would settle the question:
  - unit: calls;
  - attributed means: touched paths resolve to exactly one repo, else the session's majority repo, and the workspace root never counts;
  - pass: ≥80%;
  - data: a clean scratch re-ingest.
  
  Fail means park attribution permanently.
- A3, A4 and A14 contaminate any re-measurement in both directions (c 85), so measure on a scratch DB after fix #1.

---

## 5. Open questions for the owner

| # | Question | Why it matters | Conf. it matters |
|---|---|---|---|
| Q1 | Is the workspace root itself a Git repo? | Decides whether ADR 0005's 98.5% is mostly root sessions under the root's name (§4.9). One local query on a DB *copy* answers it. | 85 |
| Q2 | Is the daily launchd ingest currently active? | If yes, A15 means STATUS's "no historical re-ingest is authorized" is already being violated nightly for every surviving transcript. | 85 |
| Q3 | Are any M1 (LiteLLM) rows in the real DB, and are their `ts` values naive? | If yes, `doctor` may already crash or misreport (A6). | 70 |
| Q4 | What is Claude Code's transcript retention on your machine (`cleanupPeriodDays`)? | Determines how quickly rows become irreplaceable (the A15 mix of pricing versions) and how much history a key-change migration (top change #1) can re-derive. | 75 |
| Q5 | Should the ledger be append-only (usage facts plus derived cost), or is "latest re-derivation wins" acceptable? | This is the core design decision behind top change #1. It needs an ADR either way, and the current docs imply the former while the code does the latter. | 85 |
| Q6 | Is the recovery prompt ever fed to an agent automatically (no human read)? | If yes, A7 moves from High to Critical. | 80 |
| Q7 | Should `docs/` and fixtures keep the OS username, home layout and private project names, given the repo is public? | The earlier draft flagged these as personal identifiers. They are not credentials, but they are content the README says stays local. I have not repeated them here. | 70 |
| Q8 | Is a replay number still being used for FS-2/M2.5 decisions? | If yes, pause until A2 and A21 are fixed. | 80 |

---

## 6. Dependency advisories (2026-11-03)

- **Method:** I sent one `POST https://api.osv.dev/v1/querybatch` covering all 89 versioned packages in `uv.lock` (the editable project excluded), then fetched each GHSA record from `api.osv.dev/v1/vulns/{id}` for severity and fixed version. No other host was contacted. PYSEC entries are omitted where they alias a listed GHSA.
- **Reachability:**
  - The repo imports `litellm` only for the `CustomLogger` callback base (`ingest/litellm_proxy.py`).
  - Its own code makes **no outbound HTTP calls**, and no module imports `aiohttp`, `anyio`, `requests` or `urllib3` directly (checked by grep).
  - "Reachable" below means reachable from this repo's own code paths. A host process that registers the callback and makes LiteLLM calls has its own exposure.
- **Result:** 9 of 89 packages have advisories. **None is reachable from this repo's own code paths** (c 75). Two dev tools are the realistic exposure: `pytest` tmpdir handling on shared CI runners, and `virtualenv`, pulled in by `pre-commit`. Every fixed version sits inside the declared ranges in `pyproject.toml`, so `uv lock --upgrade-package <name>` resolves all of them without loosening a constraint (c 80).

| package | version | advisory ID | severity (max) | affected path in this repo? | confidence |
|---|---|---|---|---|---|
| litellm | 1.91.0 | GHSA-7hp6-4w63-5g45, GHSA-g5ff-637f-6q2m, GHSA-3cv6-jpf6-8222 (fixed ≥1.95.0 / 1.100.4+ line) | HIGH | **No.** All three target the LiteLLM **Proxy server** (admin salt-key reuse, `vertex_ai_credentials` file read, request-body SSRF). This repo imports only `CustomLogger` and never runs the proxy. | 80 |
| aiohttp | 3.14.1 | GHSA-2g87-pp6c-29x5, -5wr8-gcqf-gqf3, -9xw5-w5jj-pvcg, -cq5v-8q36-5273, -494j-54xm-rwp3, -6cjc-53gc-5rqm, -f9xw-jh8m-3mwq, -gx76-c99x-2c96, -mfx4-hv73-q22v, -mq44-7p77-q5h7, -pqxq-w44r-73xw (fixed 3.14.4) | HIGH | **No** for this repo. It is transitive via litellm, most advisories are **server-side**, and the console runs on uvicorn/starlette, not aiohttp. Client-side items (response parser OOB read, cookies) matter only in a host process that makes LiteLLM calls. | 75 |
| anyio | 4.14.1 | GHSA-82r6-8w77-94w6, GHSA-3w57-8xmc-8v26, GHSA-5p39-cfhj-2xmp (fixed 4.14.2) | CRITICAL | **No.** Used by starlette/httpx for the event loop. The advisories concern `TLSStream` IDNA encoding, `run_process` `extra_groups`, and process-pool stderr. The repo uses none of these: subprocesses go through stdlib `subprocess`, and the console has no TLS. | 75 |
| certifi | 2026.6.17 | GHSA-6q48-6c7w-9gw2 (fixed 2026.10.18) | CRITICAL | **No** for this repo, which makes no outbound TLS. It does affect any outbound HTTPS from a LiteLLM host process (httpx/requests trust store). | 80 |
| urllib3 | 2.7.0 | GHSA-8988-9cw3-xx77, GHSA-vxq7-64xx-v4gw, GHSA-gh4c-6fx4-qh6g (fixed 2.8.0) | HIGH | **No.** Reached via requests → tiktoken → litellm (tokenizer download). There are no direct calls. | 70 |
| multidict | 6.7.1 | GHSA-54p9-h82j-f925 (fixed 6.9.1) | MODERATE | **No.** Reference leak in set ops, transitive via aiohttp. | 85 |
| pytest | 8.4.2 | GHSA-6w46-j5rx-g56g (fixed 9.0.3) | MODERATE | **Dev only.** Vulnerable `tmpdir` handling. Many tests use `tmp_path`, so this is relevant on shared multi-user runners, not on single-user GitHub-hosted CI. The fix is a major version bump (8 → 9), so check plugin compatibility. | 75 |
| virtualenv | 21.5.1 | 23 GHSAs, e.g. GHSA-94p9-xgh2-xp45 (seed wheels not integrity-checked), GHSA-p58f-9548-mpm2 / -5vjq-rrrf-7h2q / -c978-59m8-c77v (activation-script command injection) (fixed 21.14.9) | HIGH | **Dev only.** Pulled in by `pre-commit`, which creates hook environments with it. Exposure is a hostile environment name or path on a developer machine, or tampered seed wheels. | 75 |
| filelock | 3.29.5 | GHSA-v4x8-3wr5-3wq8, GHSA-69hj-f68j-2879, GHSA-j8f7-rjxc-mr56 + 6 more (fixed 4.2.1) | HIGH | **Dev/indirect only.** Pulled in by virtualenv and huggingface-hub. Multi-user lock-file symlink and truncation issues. The repo never uses filelock itself. | 75 |

Caveats:
- OSV data is as of this query, and the severities are the advisory database's own ratings, not mine.
- "Not reachable" comes from import and usage inspection of this repo, not from running the dependencies' code paths (c 75 overall).

---
_Report only. No source, test, config or other docs file was changed. Repro scripts lived outside the repository and were not committed._
