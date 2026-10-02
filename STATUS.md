# agent-ledger Status

Last updated: 2026-10-02 (ADR 0007 — usage de-duplicated by `message.id`;
LIVE on local `main`, production DB re-ingested; not pushed)

## Current Baseline

- **Cost was overstated ~2.2x by per-line usage summing — fixed and live**
  (2026-10-02, ADR 0007, `MODEL_VERSION` 4; merged to local `main`, production
  `data/ledger.db` re-ingested after a backup,
  `data/ledger.db.pre-dedupe-2026-10-02.bak`; the nightly launchd ingest now
  runs the fixed code). Live total moved $2,923.71 -> $2,504.79 (443 rows). One API response spans several transcript lines sharing a `message.id`;
  every line was added. Full corpus: line-sum $1,013.62 vs de-duplicated
  $456.31 (2.22x; 2.13–2.36x in each month). The like-for-like
  change on identical input was $2,931.17 → $2,499.33 (−14.7%); it is not larger because 310 rows
  ($2,162.20, `model_version` < 4) have no surviving transcript and stay
  overstated. **Treat any pre-v4 Claude Code figure as an upper bound,
  including the `$1,596.36` / `$2,570.83` totals quoted below and in ADR
  0006.** Open, larger-than-expected: subagent transcripts reuse the parent
  `sessionId`, so `upsert` overwrites instead of adding — $121.27 (26%) of
  corpus spend never reaches the DB (ADR 0007 follow-up #1, needs its own ADR).

- **Attribution fix v2 is implemented and verified against real production
  data** (2026-08-02, ADR 0005): the M0 kill criterion that fired twice
  (2026-07-06 original, then again after the cwd-basename rescope) is now
  fixed at the root — attribution keys on git repo identity
  (`ingest/git_label.py`), not a cwd/launch-directory basename, and never
  silently falls back to one. `CallRecord` gained `repo_name`/
  `worktree_name`/`branch`/`cwd_raw`/`label_source` (schema v2, migrated
  in place, no data loss). A 26-day silent ingestion gap
  (2026-07-06 -> 2026-08-01) was found and closed: a `collector_heartbeat`
  table + `agent-ledger doctor` make the next gap visible, and a real
  launchd agent (`com.yashshrivardhankar.agent-ledger.ingest`, loaded and
  verified) now runs `ingest` daily so there doesn't need to be a next
  gap. Production `data/ledger.db` was migrated, idempotency-verified
  (two consecutive real `ingest` runs produced identical totals), and
  backfilled (`scripts/backfill_labels.py`, one-off): 45 pre-fix rows
  proven superseded by a reprocessed v2 row were deleted, 74 more with a
  still-resolvable path were relabeled, 81 whose source transcript no
  longer exists were left honestly `label_source='unknown'` — their
  tokens/cost untouched. Final state: 342 rows, $1,596.36. Of cost where a
  cwd was actually recorded, 98.5% now resolves via git (the ~26%
  unattributed share on the *full* corpus is 100% irreplaceable pre-fix
  legacy debt, not a defect in the new path — see ADR 0005 Consequences).
- Known Gaps' "Per-project attribution remains below threshold" entry
  below is superseded by this fix; kept for history.

- **M0, M1, M2 are all built and verified against real data** (2026-07-05),
  not just fixtures: M0 (historical ledger + per-project report), M1 (litellm
  live-capture callback, proven end-to-end with one real Ollama completion,
  async-write race documented), M2 (counterfactual replay: $544.18 real
  historical spend, $295.12 ceiling savings across 82 unique calls, 100%
  modeled for Anthropic).
- **M3.a (Ending Detector) is built, tested, and committed** (2026-07-06):
  Exposes ending classification (`completed`, `interrupted_limit`, `interrupted_abort`, `unknown`) over Claude Code transcripts. Employs git commit timestamp correlation (`[-10 mins, +15 mins]` window around last activity) and transcript tail analysis (looking for mode normal, ai-title, last-prompt, rate-limit, and network errors).
  The CLI command `agent-ledger resume --list` is fully implemented and renders the table over the real corpus without error.
- **M3.b Verified Recovery Console is implemented** (2026-07-17, ADR 0003):
  `agent-ledger recover` emits provider-neutral `RecoveryBrief` v1 JSON or a
  safe prompt, and `agent-ledger demo` runs the exact disposable before/after
  judge path. Transcript commands/results remain untrusted, Git inspection is
  fixed and read-only, unsafe paths fail closed, and the localhost console is
  protected by capability token, Host/Origin allowlists, no CORS, no-store,
  and restrictive CSP.
- **Recovery Loop v1 Packets 1-3 are implemented and verified** (2026-07-18,
  ADR 0004): the provider-neutral adapter seam supports declared Claude Code
  and Codex JSONL formats, Codex calls pair with outputs only by exact call ID,
  discovery binds candidates to the exact trusted Git root, and contained
  absolute paths normalize safely. Raw call arguments and output bodies do not
  enter public evidence models. `agent-ledger console --repo PATH` now opens an
  immutable Recovery Inbox with lazy digest-checked selection, redacted failure
  states, filters, responsive layouts, and compatibility for the original
  explicit-session console. CLI-only verification now produces content-fresh,
  private receipts and canonical downloadable packages without retaining argv
  or process output. Packet 4 remains to be implemented.

## Verification

The complete project gate passes (Ruff format, Ruff check, MyPy strict, and PyTest):

```bash
.venv/bin/ruff format --check src/ tests/
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src
.venv/bin/pytest
```

Result (2026-08-02, Attribution fix v2 checkpoint): 100 tests passing,
86.24% total coverage; Ruff format/check and MyPy strict also pass.

Result (2026-07-18, Packet 3 checkpoint): 82 tests passing, 85.65% total
coverage; Ruff format/check and MyPy strict also pass. Structure-only dogfood
against the real recovered Codex rollout found 277 tool attempts, 276 matched
outputs, and one unmatched attempt; the adapter classified it as interrupted
and discovered it only within the trusted repository boundary. A real Inbox
run over the workspace discovered 20 bound candidates and excluded 18; desktop
at 1280px and narrow 390px renders had no horizontal overflow or console
errors. The real localhost smoke cycle starts, fetches all product endpoints,
stops, and cleans its synthetic repository. Browser review passes at 1440px
desktop and 390px mobile; the mobile document has no horizontal overflow,
keyboard skip/copy works, and the console reports zero errors or warnings. A
fresh wheel was installed into an isolated Python 3.11 environment; packaged
HTML/CSS/JS/favicon/demo assets were present and its demo smoke passed.

## Build Week Publication

- The public repository is live at
  `https://github.com/shrivardhankaryash007/agent-ledger`. Commit `ec5c1e5`
  adds factual Codex/GPT-5.6 provenance; the complete local quality gate was
  rerun and passed before publication.
- The Devpost draft is complete through the finalization screen: it includes
  the public repository, an evidence-backed Codex Session ID, and local
  installation/testing instructions. It remains intentionally unsubmitted.

## Known Gaps

- **Per-project attribution remains below threshold after rescope:** 57.8%
  of call volume is now project-specific on the real corpus, but the M0 kill
  threshold is >=80%. **Superseded 2026-08-02 (ADR 0005):** attribution now
  keys on git repo identity; 98.5% of cost with a recorded cwd resolves.
  Kept here for history — see "Current Baseline" above for the current
  number.
- A Build Week-ready public YouTube demo (under three minutes) is not yet
  available; final Devpost submission remains intentionally deferred.
- Packet 4 still needs the multi-provider installed-wheel demo, descendant
  process and interrupted-write fault injection, final browser receipt states,
  and the physical-keyboard pass. Gemini remains deliberately deferred.
- The in-app browser automation did not synthesize native Enter-key button
  activation even with focus correctly restored. A physical-keyboard pass
  remains part of the final UI gate; pointer navigation and focus restoration
  are verified.

## Next Useful Work

- `data/ledger.db.pre-backfill-2026-08-02.bak` is a safety snapshot from
  before the 2026-08-02 backfill ran (gitignored, not committed) — safe to
  delete once the final numbers above have been reviewed.
  `scripts/backfill_labels.py` was written for that one-off run only, not
  as a permanent tool; a second run today is a harmless no-op (no
  `model_version=1` rows remain) but it isn't meant to become a recurring
  command.
- Implement Recovery Loop v1 Packet 4: extend the disposable demo across Inbox
  → Brief → Receipt → Package, add the remaining fault-injection gates, verify
  the built wheel and physical keyboard path, then refresh README and handoff
  evidence. The public demo video, M3.c passive dogfood, attribution rescope,
  and Penny capture integration remain deferred.
