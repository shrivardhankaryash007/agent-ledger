# agent-ledger — Agent Operating Rules

This project is governed by the workspace Coding Constitution
(`~/dev/standards/coding-constitution/CODING-CONSTITUTION.md`) and the
workspace handoff contract (`~/dev/standards/agentic-os/HANDOFF-CONTRACT.md`).
Read `docs/architecture.md` before any work; it is the plan of record for
module boundaries and milestones.

## Project-specific overrides and hard rules

1. **Core is frozen except via version bump.** `src/agent_ledger/ledger/`
   (the `CallRecord` model, the `CallRecordSource` protocol, the repository
   API) may not change shape without a migration + version bump. Collected
   spend data is the compounding asset; it must survive every iteration.
   Agents may add sources/policies/reports freely without touching core.
2. **Do not modify `~/dev/scripts/token_ledger.py` or `ide_meter.py`.**
   agent-ledger ingests from the same raw Claude Code transcript source
   independently; it does not merge with or alter the existing workspace
   ledger.
3. **No cloud calls in M0/M1 ingestion.** Ingestion reads local transcripts
   and local pricing tables only.
4. **Milestone gates (see `docs/architecture.md`):** mypy --strict, ruff,
   ≥80% coverage on touched modules, hypothesis property tests on cost math
   (non-negativity, sum invariants), golden-file regression on report output.
5. **Write the failing acceptance test before the implementation.** Every
   milestone's acceptance criterion in `docs/architecture.md` must exist as
   a test that fails for the stated reason before code is written to pass it.
6. **ADR 0028 (workspace):** commit your own work at session end with a
   conventional message; write the session log; update STATUS.md. Never push
   without an explicit ask.
7. **Port:** `8680`, registered in `~/dev/standards/PORTS.md`. Never default
   to 8000.
