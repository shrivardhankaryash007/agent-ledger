# agent-ledger Status

Last updated: 2026-07-06

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
- **Rescope decided (2026-07-06, Claude Code): rescope, not hold/abandon.**
  Real-transcript inspection (not guessed) found each JSONL line already
  carries a per-line `cwd` field that tracks the actual working directory at
  that message, and it changes mid-session (confirmed: a root-started
  session whose `cwd` later shows `/Users/yashshrivardhankar/dev/careledger`).
  `EXECUTION-PACKET-m0-cwd-attribution.md` (packet-lint clean, `--run`
  confirmed red) specs bucketing by `(model, cwd-derived-project)` instead of
  `model` alone, replacing `path.parent.name` with `Path(cwd).name` per line
  when `cwd` is present. Ready for Codex to execute. Re-running the real
  ingest and re-checking the 80% threshold is the owner's step after that
  lands, not part of the packet.
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

- **Per-project attribution is broken for the dominant call source** (see
  Current Baseline) — this is the live, unresolved gap, not a deferred
  milestone.
- M2.5 (governable-traffic soak) and M3 (budget wallet) remain deferred per
  `docs/architecture.md` and the FS-2 decision.
- Not yet registered in `AGENTS.md`'s Active Projects table with its current
  M0-M2 state (still reads "M0 scaffolded... not yet built").

## Next Useful Work

- **Hand `EXECUTION-PACKET-m0-cwd-attribution.md` to Codex.** One file to
  edit (`src/agent_ledger/ingest/claude_transcripts.py`), one red test
  already written and confirmed failing for the right reason
  (`tests/test_m0_cwd_attribution.py`). Frontier/owner reviews the diff
  before committing per the packet's §7.
- After that lands: re-run the real ingest (`uv run agent-ledger ingest
  ~/.claude/projects && uv run agent-ledger report`) and re-check the 80%
  attribution threshold against real data, not fixtures.
- M2.5 (route Penny's LLM calls through the litellm capture point; 5-day
  soak; kill if <10 governable calls/day sustained) can proceed in parallel
  — it is about traffic routing, not attribution, and does not depend on
  the packet above.
