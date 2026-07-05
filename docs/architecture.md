# Architecture

Source of truth for the product plan: vault
`50-Systems/Fable-Sprint-2026-07/2026-07-03-fable-selection-plans.md`
("Product-grade execution plan: agent-ledger"). This file is the working
copy an executor reads day-to-day; the vault file is the record of the
decision.

## Module boundaries (agent-proof — do not cross without a version bump)

- `ledger/` — core domain. `CallRecord` pydantic model, SQLite repository,
  migration runner, versioned pricing tables (YAML). No module may write to
  the DB except through this repository.
- `ingest/` — source plugins implementing a `CallRecordSource` protocol,
  removable without touching core.
  - M0: `claude_transcripts.py` — reads `~/.claude/projects/<project-dir>/*.jsonl`
    directly (independent of `~/dev/scripts/ide_meter.py`), captures
    `project = path.parent.name` (the one gap found in the existing
    workspace ledger — see ADR 0001... no, see prior-art audit note below).
  - M1: LiteLLM proxy callback (live capture).
- `policy/` — routing policy engine (M2). Pure functions, no I/O.
- `report/` — polars aggregations: per-project/per-model spend, counterfactual
  replay. Output is plain dataclasses/frames (UI-agnostic).
- `api/` + `cli/` — FastAPI read endpoints (Desk widget consumer) and typer
  commands (`agent-ledger ingest`, `agent-ledger report`, later `replay`,
  `budget`).

## Prior-art note (2026-07-05 audit)

`~/dev/scripts/token_ledger.py` + `ide_meter.py` already implement JSONL
ledger recording and transcript backfill for the whole workspace. They are
NOT modified by this project. The one real gap found: `ide_meter.py` walks
`~/.claude/projects/**/*.jsonl` but discards the per-project directory name,
so the existing workspace ledger has zero project attribution today.
agent-ledger's M0 ingest source re-implements the same parse/classify logic
independently and captures that directory name as `project` — this is the
mechanism the M0 acceptance test in `tests/test_m0_ingest_report.py` checks.

## Milestones

- **M0 — historical ledger.** Scaffold + `CallRecord` + repository +
  migrations + Claude Code transcript ingester + `report per_project`.
  *Acceptance:* real historical spend from existing Claude Code transcripts
  renders as a per-project table (`tests/test_m0_ingest_report.py`).
  *Kill:* if <80% of transcript calls can be attributed to a project within
  3 evenings, rescope attribution before continuing.
- **M1 — live capture.** LiteLLM proxy source + pricing tables + caller-tag
  attribution. *Acceptance:* 5 consecutive days of live traffic captured
  alongside batch ingest. *Kill (proxy source only):* day 5 with <~100 live
  calls → drop the proxy plugin, continue batch-only.
- **M2 — counterfactual replay.** Policy engine + `replay`: re-route the last
  N calls per the workspace's §8 routing policy, measure savings with stated
  assumptions. *Acceptance:* replay over ≥500 real calls yields a savings
  number. *Kill:* if >50% of calls require guessing whether local would have
  sufficed, stay observability-only. **This milestone's result is the FS-2
  Fable session trigger — see vault roadmap.**
- **M3 — budget wallet.** Per-agent token budgets; enforcement hook + Desk
  endpoint. *Acceptance:* an agent run halts/asks when budget is exhausted,
  visible in the Desk. *Kill:* constant owner override in week 1 → advisory
  mode only.

## Gates per milestone close

mypy --strict, ruff, ≥80% coverage on touched modules, hypothesis property
tests on cost math (non-negativity, sum invariants, rounding), golden-file
regression tests on report outputs.
