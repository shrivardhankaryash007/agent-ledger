---
status_version: 2
project: agent-ledger
updated: 2026-10-29
head: 3bfde79
---

# agent-ledger Status

## Current Slice

- req: Correct modeled replay ceiling and Claude cache-write TTL cost accounting
- state: O1/O4 implementation and verification complete; scoped commit ready for integration
- owner: Codex recovery-agent-ledger, 2026-10-29
- goal: Exclude unsupported calls from replay savings and price 1-hour Claude cache writes at 2x effective input without changing frozen ledger/schema shape.

## Verified Baseline

- Pricing sync (2026-10-25): generated YAML now includes the three missing catalog rows; `model_catalog.py ledger-sync --check` passes; focused pricing tests 12 pass. Full gate passes: 150 tests / 87.31% coverage, Ruff/format and mypy. Disposable server/wheel checks rerun with host loopback/cache permissions after sandbox refusal. No core schema or historical record changes.
- Full gate: `env PYTHONPATH="$PWD/src" /Users/yashshrivardhankar/dev/agent-ledger/.venv/bin/pytest -q` -> 155 passed, 87.36% total coverage, 1 existing Starlette deprecation warning. Touched modules: `claude_transcripts.py` 99%, `pricing.py` 95%, `replay.py` 93%.
- `.venv/bin/ruff format --check src/ tests/` -> 64 files already formatted; `.venv/bin/ruff check src/ tests/` -> pass; `.venv/bin/mypy --strict src` -> 40 files pass; `git diff --check` -> pass.

- `.venv/bin/ruff format --check src/ tests/ && .venv/bin/ruff check src/ tests/ && .venv/bin/mypy src && .venv/bin/pytest` -> pass, 150 tests / 87.31% coverage / 2026-10-22
- `report --by context` added (mean cached context per call; `no-cache-data` band kept separate) -> 140 tests pass / 2026-10-12
- `context-check` (pre-registered PASS/NO-IMPROVEMENT/INSUFFICIENT) + one-shot launchd 2026-10-19 08:30 -> 145 tests pass / 2026-10-12
## Dirty / In-Flight

- `src/agent_ledger/policy/replay.py`, `src/agent_ledger/ledger/pricing.py`, `src/agent_ledger/ingest/claude_transcripts.py` | O1/O4 correction; no core-model or schema edits
- `tests/test_m2_replay.py`, `tests/test_m3_cache_tokens.py`, `tests/test_pricing_tiers.py`, `tests/test_m0_units.py` | regression/property coverage
- `docs/decisions/0009-cache-ttl-pricing-and-modeled-replay-ceiling.md`, `plans/cache-ttl-and-replay-ceiling/plan.mdx`, `STATUS.md` | rationale, plan, status
- `.code_graph/` | generated cache; preserve

## Decisions / Pointers

- ADR 0003 | M3.b Recovery Console: provider-neutral `RecoveryBrief` v1; localhost console behind capability token, Host/Origin allowlists, no CORS, CSP
- ADR 0004 | Recovery Loop v1 adapter seam (Claude Code + Codex JSONL), exact call-ID pairing, trusted Git root binding; raw args/outputs never enter public evidence
- ADR 0005 | attribution keys on git repo identity (`ingest/git_label.py`), schema v2; `collector_heartbeat` + `agent-ledger doctor`; daily launchd `com.yashshrivardhankar.agent-ledger.ingest`
- ADR 0007 | per-message dedupe, `MODEL_VERSION` 4; pre-v4 Claude Code figures are upper bounds (ADR 0006 totals too)
- ADR 0008 | subagent transcripts get `:subagent:<file stem>` row-key suffix; long-prompt pricing tiers in `pricing.yaml`
- ADR 0009 | Claude 1-hour cache writes priced at 2x effective input rate at ingestion; replay ceiling includes only modeled calls; no schema change or historical rewrite
- `plans/cache-ttl-and-replay-ceiling/plan.mdx` | red-first fix and verification plan
- ADR 0059 (workspace) | `pricing.yaml` generated from `standards/agentic-os/model-catalog.json`; Sonnet 5.5 cache-read corrected to $0.10/MTok
- Public repo: `https://github.com/shrivardhankaryash007/agent-ledger`; Devpost draft complete but intentionally unsubmitted

## Known Gaps

- 310 rows ($2,162.20, `model_version` < 4) lack surviving transcripts and stay overstated; rows without transcript keep the old higher Sonnet 5.5 cache-read cost.
- Existing collected rows are not rewritten by the O4 fix. Correcting historical 1-hour cache costs requires a separately reviewed, deliberate re-ingest/replay.
- Public YouTube demo (under 3 min) not available; final Devpost submission deferred.
- In-app browser automation did not synthesize native Enter activation; physical-keyboard pass remains for visual testing. Gemini adapter deferred.
- `data/ledger.db.pre-backfill-2026-08-02.bak` (gitignored) is safe to delete after review; `scripts/backfill_labels.py` was a one-off, not a recurring tool.

## Next Action

- Complete full gates, commit the scoped O1/O4 fix, then coordinate hash-checked integration; no historical data re-ingest is authorized.

## Cold History

- archive: `docs/archive/status/2026-10.md` (SHA-256 `0059c369c5610aa8870458928f6538e446f329235f7366c39d388c27688a8f4e`)
- sessions: workspace `python3 scripts/session_index.py tail --lines 5`
- commits: `git log -- STATUS.md`
