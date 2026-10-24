---
status_version: 2
project: agent-ledger
updated: 2026-10-25
head: d699215
---

# agent-ledger Status

## Current Slice

- req: Recovery Loop v1 Packet 4 (Packets 1-4 done 2026-10-22, ADR 0004); latest landed work: Packet 4 credible demo, Codex fixture, package verification helper, fault-injection gates, and built-wheel smoke
- state: Packet 4 complete and verified; full gate green (150 tests pass, 87.31% coverage, ruff + mypy --strict pass)
- owner: Antigravity
- goal: Local-first token/cost ledger plus verified recovery console. M0–M3 complete and verified.

## Verified Baseline

- Pricing sync (2026-10-25): generated YAML now includes the three missing catalog rows; `model_catalog.py ledger-sync --check` passes; focused pricing tests 12 pass. Full gate passes: 150 tests / 87.31% coverage, Ruff/format and mypy. Disposable server/wheel checks rerun with host loopback/cache permissions after sandbox refusal. No core schema or historical record changes.

- `.venv/bin/ruff format --check src/ tests/ && .venv/bin/ruff check src/ tests/ && .venv/bin/mypy src && .venv/bin/pytest` -> pass, 150 tests / 87.31% coverage / 2026-10-22
- `report --by context` added (mean cached context per call; `no-cache-data` band kept separate) -> 140 tests pass / 2026-10-12
- `context-check` (pre-registered PASS/NO-IMPROVEMENT/INSUFFICIENT) + one-shot launchd 2026-10-19 08:30 -> 145 tests pass / 2026-10-12
- Same gate after ADR 0008 / pricing-tier work -> 136 tests pass / 2026-10-08
## Dirty / In-Flight

- `.code_graph/` | generated cache; preserve

## Decisions / Pointers

- ADR 0003 | M3.b Recovery Console: provider-neutral `RecoveryBrief` v1; localhost console behind capability token, Host/Origin allowlists, no CORS, CSP
- ADR 0004 | Recovery Loop v1 adapter seam (Claude Code + Codex JSONL), exact call-ID pairing, trusted Git root binding; raw args/outputs never enter public evidence
- ADR 0005 | attribution keys on git repo identity (`ingest/git_label.py`), schema v2; `collector_heartbeat` + `agent-ledger doctor`; daily launchd `com.yashshrivardhankar.agent-ledger.ingest`
- ADR 0007 | per-message dedupe, `MODEL_VERSION` 4; pre-v4 Claude Code figures are upper bounds (ADR 0006 totals too)
- ADR 0008 | subagent transcripts get `:subagent:<file stem>` row-key suffix; long-prompt pricing tiers in `pricing.yaml`
- ADR 0059 (workspace) | `pricing.yaml` generated from `standards/agentic-os/model-catalog.json`; Sonnet 5.5 cache-read corrected to $0.10/MTok
- Public repo: `https://github.com/shrivardhankaryash007/agent-ledger`; Devpost draft complete but intentionally unsubmitted

## Known Gaps

- 310 rows ($2,162.20, `model_version` < 4) lack surviving transcripts and stay overstated; rows without transcript keep the old higher Sonnet 5.5 cache-read cost.
- Public YouTube demo (under 3 min) not available; final Devpost submission deferred.
- In-app browser automation did not synthesize native Enter activation; physical-keyboard pass remains for visual testing. Gemini adapter deferred.
- `data/ledger.db.pre-backfill-2026-08-02.bak` (gitignored) is safe to delete after review; `scripts/backfill_labels.py` was a one-off, not a recurring tool.

## Next Action

- Public demo video (under 3 min), M3.c passive dogfood, attribution rescope, and Penny capture integration.

## Cold History

- archive: `docs/archive/status/2026-10.md` (SHA-256 `8eb5dfbe33917ebcf9f8c1031147de801f1fa80164539e7fc7cf00e6df28821b`)
- sessions: workspace `python3 scripts/session_index.py tail --lines 5`
- commits: `git log -- STATUS.md`
