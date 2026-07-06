# agent-ledger Status

Last updated: 2026-07-06 (evening — Fable scope decision landed)

## Current Baseline

- **M0, M1, M2 are all built and verified against real data** (2026-07-05),
  not just fixtures: M0 (historical ledger + per-project report), M1 (litellm
  live-capture callback, proven end-to-end with one real Ollama completion,
  async-write race documented), M2 (counterfactual replay: $544.18 real
  historical spend, $295.12 ceiling savings across 82 unique calls, 100%
  modeled for Anthropic). Full detail in
  `standards/agentic-os/sessions/2026-07-05-1600-claude-code.md`.
- **FS-2 decision (2026-07-05):** M3 (budget wallet) is approved in
  principle but gated behind a new milestone, **M2.5 — "governable traffic
  exists"** (route one real workflow through the litellm capture point, run
  the 5-day soak M1's acceptance criterion skipped). Full reasoning in
  `standards/agentic-os/sessions/2026-07-05-1700-claude-code.md`.
- **M0's attribution kill-criterion has now actually been checked against the
  real transcript corpus, and it fails (2026-07-06, Antigravity/gemini-cli
  session):** ingesting 140 transcript files under `~/.claude/projects/`
  attributes only **11.6%** of calls to a specific project directory; 88.4%
  fall under the workspace root because Claude Code is normally invoked from
  `~/dev`, not from inside a project directory. The M0 design doc flagged
  this exact risk (`docs/architecture.md`'s "Prior-art note") and set an
  explicit <80% kill threshold — it was not checked before M1/M2 were built
  same-session, and now that it has been, it fires. **This does not
  invalidate M2's $295 ceiling** (that number is total-spend/model-tier, not
  per-project), but the per-project spend view — half of M0's stated
  acceptance criterion — is broken by construction today.
- **Rescope landed (2026-07-06, Gemini High):** Implemented per-line `cwd` tracking
  and bucketing by `(model, project)` inside `src/agent_ledger/ingest/claude_transcripts.py`.
  If `cwd` is present in the JSONL line, the project is derived as `Path(cwd).name` and
  session_id is suffixed with `:{project_name}` to prevent SQLite primary key conflicts.
  Otherwise, it falls back to the directory name `path.parent.name` and the base session_id.
  All checks and tests pass with 80.49% coverage.
- **Post-rescope real ingest still fails the attribution kill line
  (2026-07-06, Codex):** `uv run agent-ledger ingest ~/.claude/projects &&
  uv run agent-ledger report` ingested 204 records into `data/ledger.db`, but
  call-weighted attribution is only **57.8% specific** versus **42.2%**
  still bucketed under `-Users-yashshrivardhankar-dev`. This is an improvement
  over the original 11.6% specific result, but it remains below the explicit
  80% M0 kill threshold.
- Repository writes are idempotent on `(session_id, model_sku)` and reject an
  unsupported schema version.

## Verification

The complete project gate passes:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Result (2026-07-05, M2 checkpoint): tests passing, coverage above the 80%
floor on all touched modules. Re-run before any further work to confirm no
drift.

## Dirty / In-Flight State

- Clean as of the M2 session-end commit (`ed5638b`). No pre-existing dirty
  paths.

## Known Gaps

- **Per-project attribution remains below threshold after rescope:** 57.8%
  of call volume is now project-specific on the real corpus, but the M0 kill
  threshold is >=80%. The remaining workspace-root bucket needs a second
  attribution strategy before per-project spend should be treated as reliable.
- M2.5 (governable-traffic soak) and M3 (budget wallet) remain deferred per
  `docs/architecture.md` and the FS-2 decision.
- Not yet registered in `AGENTS.md`'s Active Projects table with its current
  M0-M2 state (still reads "M0 scaffolded... not yet built").

## Next Useful Work

- **Scope decision landed (2026-07-06, Fable):** the next milestone is
  **M3 — Resume Packet (continuity surface)**, before any further
  routing/cost work. Decision memo: `docs/decisions/0002-continuity-before-
  routing.md`. Milestone plan (Codex-executable, packets to be cut by
  Sonnet): `EXECUTION-PLAN-m3-resume-packet.md`. First packet to cut:
  M3.a corpus recon + ending detector.
- **Attribution rescope #2 is demoted** to a gated precondition of the
  routing/cost surfaces only (M4 budget wallet, replay-derived
  recommendation claims). The resume packet is per-session and does not
  depend on the 80% per-project line. Original rescope note preserved:
  inspect the `-Users-yashshrivardhankar-dev` bucket; recover project from
  transcript metadata, file activity, or a deliberate "workspace-root"
  category.
- M2.5 (route Penny's LLM calls through the litellm capture point; 5-day
  soak; kill if <10 governable calls/day sustained) stays parallel and
  non-blocking — it is about traffic routing, not attribution.
