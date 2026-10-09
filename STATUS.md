---
status_version: 2
project: agent-ledger
updated: 2026-10-10
head: d699215
---

# agent-ledger Status

## Current Slice

- req: Recovery Loop v1 Packet 4 (Packets 1-3 done 2026-07-18, ADR 0004); latest landed work: ADR 0008 subagent row keys, long-prompt pricing tiers, `report --by model` (2026-10-08)
- state: Packet 4 not started; M0 attribution kill-criterion status needs owner confirmation (see Known Gaps)
- owner: owner
- goal: Local-first token/cost ledger plus verified recovery console. M0, M1, M2 built and verified on real data; M3.a, M3.b done.

## Verified Baseline

- `.venv/bin/ruff format --check src/ tests/ && .venv/bin/ruff check src/ tests/ && .venv/bin/mypy src && .venv/bin/pytest` -> pass, 100 tests / 86.24% coverage / 2026-08-02
- Same gate after ADR 0008 / pricing-tier work -> 136 tests pass / 2026-10-08
- Real ledger re-ingest on copies (ADR 0008) -> +$128.62 equal to 36 subagent rows ($128.63), no double count / 2026-10-08
- Production re-ingest after ADR 0007 dedupe fix -> total $2,923.71 -> $2,504.79 (443 rows) / 2026-10-02
- Attribution v2 on production data -> two consecutive ingests identical; 98.5% of cost with recorded cwd resolves via git / 2026-08-02
- Not re-run on 2026-10-10 (status migration only)

## Dirty / In-Flight

- none

## Decisions / Pointers

- ADR 0003 | M3.b Recovery Console: provider-neutral `RecoveryBrief` v1; localhost console behind capability token, Host/Origin allowlists, no CORS, CSP
- ADR 0004 | Recovery Loop v1 adapter seam (Claude Code + Codex JSONL), exact call-ID pairing, trusted Git root binding; raw args/outputs never enter public evidence
- ADR 0005 | attribution keys on git repo identity (`ingest/git_label.py`), schema v2; `collector_heartbeat` + `agent-ledger doctor`; daily launchd `com.yashshrivardhankar.agent-ledger.ingest`
- ADR 0007 | per-message dedupe, `MODEL_VERSION` 4; pre-v4 Claude Code figures are upper bounds (ADR 0006 totals too)
- ADR 0008 | subagent transcripts get `:subagent:<file stem>` row-key suffix; long-prompt pricing tiers in `pricing.yaml`
- ADR 0059 (workspace) | `pricing.yaml` generated from `standards/agentic-os/model-catalog.json`; Sonnet 5.5 cache-read corrected to $0.10/MTok
- Public repo: `https://github.com/shrivardhankaryash007/agent-ledger`; Devpost draft complete but intentionally unsubmitted

## Known Gaps

- Owner rescope decision on the M0 attribution kill-criterion (>=80% per-project attribution) is flagged as pending in the workspace AGENTS.md. This repo's old STATUS recorded it as fixed by ADR 0005 on 2026-08-02 (98.5% of cost with recorded cwd resolves; ~26% of full-corpus cost is irreplaceable pre-fix legacy). No pending-decision text exists in this repo's AGENTS.md. Next: owner confirms whether ADR 0005 closes the criterion.
- 310 rows ($2,162.20, `model_version` < 4) lack surviving transcripts and stay overstated; rows without transcript keep the old higher Sonnet 5.5 cache-read cost.
- Public YouTube demo (under 3 min) not available; final Devpost submission deferred.
- Packet 4 needs multi-provider installed-wheel demo, descendant-process and interrupted-write fault injection, final browser receipt states, physical-keyboard pass (in-app browser automation did not synthesize native Enter activation). Gemini deferred.
- `data/ledger.db.pre-backfill-2026-08-02.bak` (gitignored) is safe to delete after review; `scripts/backfill_labels.py` was a one-off, not a recurring tool.

## Next Action

- Implement Recovery Loop v1 Packet 4: extend the disposable demo across Inbox -> Brief -> Receipt -> Package, add the remaining fault-injection gates, verify the built wheel and physical keyboard path, then refresh README and handoff evidence.
  - Deferred: public demo video, M3.c passive dogfood, attribution rescope, Penny capture integration.

## Cold History

- archive: `docs/archive/status-history-through-2026-10-10.md` (SHA-256 `1d7e6baeb884ff3c64f1b5c7b43b47db1445b3f1e327c0bc1f560fa51ef8ad91`)
- commits: `git log -- STATUS.md`
