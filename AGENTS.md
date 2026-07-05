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
6. **ADR 0028 (workspace) — no exceptions, no reminders needed.** At the end
   of every session that touches this repo, regardless of which agent or
   vendor ran it: (a) commit your own work with a conventional message, (b)
   write a session log at `~/dev/standards/agentic-os/sessions/YYYY-MM-DD-
   HHMM-<provider>.md` following the schema in that directory's `README.md`
   (`provider` ∈ `claude-code`/`codex`/`cursor`/`gemini-cli`/`local`/`other`),
   (c) update `STATUS.md` if a milestone or acceptance state changed. This is
   not optional and does not require the owner to ask each time. Never push
   without an explicit ask.
7. **Port:** `8680`, registered in `~/dev/standards/PORTS.md`. Never default
   to 8000.
