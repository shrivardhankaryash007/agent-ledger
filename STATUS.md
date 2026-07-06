# agent-ledger Status

Last updated: 2026-07-06 (evening — Fable scope decision landed)

## Current Baseline

- **M0, M1, M2 are all built and verified against real data** (2026-07-05),
  not just fixtures: M0 (historical ledger + per-project report), M1 (litellm
  live-capture callback, proven end-to-end with one real Ollama completion,
  async-write race documented), M2 (counterfactual replay: $544.18 real
  historical spend, $295.12 ceiling savings across 82 unique calls, 100%
  modeled for Anthropic).
- **M3.a (Ending Detector) is built, tested, and committed** (2026-07-06):
  Exposes ending classification (`completed`, `interrupted_limit`, `interrupted_abort`, `unknown`) over Claude Code transcripts. Employs git commit timestamp correlation (`[-10 mins, +15 mins]` window around last activity) and transcript tail analysis (looking for mode normal, ai-title, last-prompt, rate-limit, and network errors).
  The CLI command `agent-ledger resume --list` is fully implemented and renders the table over the real corpus without error.

## Verification

The complete project gate passes (Ruff format, Ruff check, MyPy typecheck, PyTest with 86.31% coverage):

```bash
.venv/bin/ruff format --check src/ tests/
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src
.venv/bin/pytest
```

Result (2026-07-06, M3.a checkpoint): 41 tests passing, coverage above the 80% floor.

## Dirty / In-Flight State

- Clean as of the M3.a session-end commit (`2b21a0a`). No in-flight changes.

## Known Gaps

- **Per-project attribution remains below threshold after rescope:** 57.8%
  of call volume is now project-specific on the real corpus, but the M0 kill
  threshold is >=80%.
- M3.b (packet generation and rendering) is not yet implemented.

## Next Useful Work

- **M3.b — Packet generator + render (2–3 evenings):** Implement deterministic extraction (first user message -> intent; Edit/Write/NotebookEdit -> touched files; Bash -> command list; final assistant text -> last_state; heuristic next-actions) and rendering to the `HANDOFF-CONTRACT.md` session-log schema.
- **M3.c — Dogfood + optional local enrichment (14-day passive window):** Optional `--llm` flag using local ollama.
- **Attribution rescope #2 is demoted** to a gated precondition of the
  routing/cost surfaces only.
- M2.5 (route Penny's LLM calls through the litellm capture point) stays parallel and non-blocking.
