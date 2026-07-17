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
- `resume/` — transcript ending detection, narrative `ResumePacket` v1, and
  provider-specific structural evidence extraction. Evidence extraction strips
  Bash commands and tool-result bodies before crossing into recovery.
- `recovery/` — provider-neutral `RecoveryBrief` v1, fixed read-only Git
  inspection, path-containment checks, evidence assembly, and safe prompt
  rendering. It does not import or modify `ledger/`.
- `api/` — capability-protected localhost recovery console. Packaged static
  assets, no CORS, no external resources, and no mutation endpoints.
- `demo/` — disposable synthetic before/after Git scenario using the same
  recovery assembler and API as real sessions.
- `cli/` — typer commands for ledger flows plus `recover` and the exact
  reproducible `demo` judge path.

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
  attribution. *Original acceptance (superseded 2026-07-05, owner decision
  — time-boxed Fable window, no natural traffic source exists yet):* 5
  consecutive days of live traffic. No process in this workspace currently
  routes calls through any proxy — Claude Code/Codex IDE-seat traffic (the
  bulk of measured spend) goes direct to vendor APIs — so a passive 5-day
  clock would never start on its own. *Revised acceptance:* the mechanism
  is built, unit-verified against the real litellm callback contract (see
  probe below), and proven end-to-end with one real completion through a
  local Ollama model. The 5-day/100-call soak becomes a background,
  non-blocking observation once something real is later pointed at it —
  not a gate on M2.

  **Verified litellm callback contract (2026-07-05, real probe, not
  guessed):** ran `litellm.completion(model="ollama/gemma4:latest", ...,
  metadata={"caller_tag": "agent-ledger-probe"})` with a `CustomLogger`
  registered and inspected `log_success_event`'s actual arguments:
  - `kwargs["model"]` = `"gemma4:latest"` (provider prefix stripped by
    litellm; matches the plain-name convention already used in
    `pricing.yaml` and the workspace's `MODEL-PRICING.md`).
  - `kwargs["custom_llm_provider"]` = `"ollama"`.
  - `kwargs["litellm_params"]["metadata"]["caller_tag"]` = the value passed
    into `metadata=` on the call — this is the project-attribution field.
  - `kwargs["litellm_call_id"]` = a UUID, unique per call — used as
    `CallRecord.session_id` (one live call = one row, unlike M0's
    per-session aggregation).
  - `kwargs["response_cost"]` = `0.0` for Ollama — litellm's own maintained
    pricing DB; use it when present, fall back to `ledger/pricing.py`
    otherwise.
  - `response_obj.usage` has `.prompt_tokens` / `.completion_tokens`
    (litellm normalizes this across every provider).

  **Operational fact (2026-07-05, real end-to-end check, not just the
  fixture tests):** litellm fires `log_success_event` on a background
  thread, *after* `litellm.completion()` already returned to the caller.
  Wiring `AgentLedgerLoggerCallback` and immediately calling
  `report.spend.per_project()` in the same script can race the write and
  see a stale/empty result — confirmed by reproducing the race, then
  confirming a short delay resolves it. Any consumer that needs
  freshly-written data right after a call (not just eventually-consistent
  reporting) must account for this; `agent-ledger report` run as a
  separate later command is unaffected.
- **M2 — counterfactual replay.** Policy engine + `replay`: re-route the last
  N calls per the workspace's §8 routing policy, measure savings with stated
  assumptions. *Acceptance:* replay over ≥500 real calls yields a savings
  number. *Kill:* if >50% of calls require guessing whether local would have
  sufficed, stay observability-only. **This milestone's result is the FS-2
  Fable session trigger — see vault roadmap.**
- **M3 — resume packet (continuity surface). Re-scoped 2026-07-06, ADR 0002.**
  Reconstruct the missing session handoff after an ungraceful ending (usage
  limit, crash) from the transcript + git state; output in the
  HANDOFF-CONTRACT session-log schema. Plan of record:
  `EXECUTION-PLAN-m3-resume-packet.md`. *Acceptance:* ≥3 real interruptions
  in a 14-day dogfood window where the packet was generated and used to
  resume. *Kill:* founder resumes without the packet in ≥⅔ of ≥3 real
  interruptions → demote to session listing, re-open routing roadmap.
  - **M3.b extension — Verified Recovery Console (2026-07-17, ADR 0003).**
    Adds an evidence-linked `RecoveryBrief` without changing `ResumePacket`.
    The transcript records attempts/results; current Git proves present state;
    neither is promoted into causal attribution. Acceptance: the disposable
    demo reports a missing verification result as unknown, rejects unsafe
    paths, serves only through a secured localhost capability, and passes the
    installed-wheel smoke path.
- **M4 — budget wallet (former M3, content unchanged).** Per-agent token
  budgets; enforcement hook + Desk endpoint. *Gated by:* M2.5 (FS-2
  decision) AND attribution rescope #2 (per-project spend must cross the
  80% line before budgets keyed on it are trustworthy — ADR 0002).
  *Acceptance:* an agent run halts/asks when budget is exhausted, visible
  in the Desk. *Kill:* constant owner override in week 1 → advisory mode
  only.

## Gates per milestone close

mypy --strict, ruff, ≥80% coverage on touched modules, hypothesis property
tests on cost math (non-negativity, sum invariants, rounding), golden-file
regression tests on report outputs.
