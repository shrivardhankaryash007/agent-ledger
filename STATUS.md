# agent-ledger Status

Last updated: 2026-07-17 (Build Week repository published; Verified Recovery Console plan awaiting owner approval)

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

The complete project gate passes (Ruff format, Ruff check, MyPy typecheck, PyTest with 87.15% coverage):

```bash
.venv/bin/ruff format --check src/ tests/
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src
.venv/bin/pytest
```

Result (2026-07-14, M3.b checkpoint): 45 tests passing, 87.15% total coverage;
the extractor is 88% covered. A real most-recent local session was rendered
to an ephemeral packet with every mandatory handoff section non-empty; the
private packet was removed immediately and was not committed.

## Build Week Publication

- The public repository is live at
  `https://github.com/shrivardhankaryash007/agent-ledger`. Commit `ec5c1e5`
  adds factual Codex/GPT-5.6 provenance; the complete local quality gate was
  rerun and passed before publication.
- The Devpost draft is complete through the finalization screen: it includes
  the public repository, an evidence-backed Codex Session ID, and local
  installation/testing instructions. It remains intentionally unsubmitted.

## Known Gaps

- **Per-project attribution remains below threshold after rescope:** 57.8%
  of call volume is now project-specific on the real corpus, but the M0 kill
  threshold is >=80%.
- A Build Week-ready public YouTube demo (under three minutes) is not yet
  available; final Devpost submission remains intentionally deferred.
- `plans/buildweek-continuity-console/plan.mdx` proposes a deterministic
  Verified Recovery Console extension. It is validated but unapproved; no
  implementation has started.

## Next Useful Work

- Owner reviews and approves or revises
  `plans/buildweek-continuity-console/plan.mdx`. Do not implement before that
  gate. If approved, begin with local Claude tool-result shape recon and failing
  RecoveryBrief evidence/safety tests.
- After the approved extension passes its judge-path gate, record the public
  under-three-minute YouTube demo, review the Devpost preview, and submit only
  after explicit owner confirmation.
- **M3.b — Packet generator + render is built and verified (2026-07-14):**
  deterministic extraction and `HANDOFF-CONTRACT.md` rendering are available
  through `agent-ledger resume [--session ID] [--project NAME] [--out PATH]`;
  malformed JSONL is skipped and counted, and no cloud calls are made.
- **M3.c — Dogfood + optional local enrichment (14-day passive window):**
  owner-paced and explicitly not started by the M3.b build; optional `--llm`
  remains a separate local-ollama-only scope.
- **Attribution rescope #2 is demoted** to a gated precondition of the
  routing/cost surfaces only.
- M2.5 (route Penny's LLM calls through the litellm capture point) stays parallel and non-blocking.
