# agent-ledger Status

Last updated: 2026-07-18 (Verified Recovery Console implemented and browser-verified; final publication assets pending)

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
- **M3.b Verified Recovery Console is implemented** (2026-07-17, ADR 0003):
  `agent-ledger recover` emits provider-neutral `RecoveryBrief` v1 JSON or a
  safe prompt, and `agent-ledger demo` runs the exact disposable before/after
  judge path. Transcript commands/results remain untrusted, Git inspection is
  fixed and read-only, unsafe paths fail closed, and the localhost console is
  protected by capability token, Host/Origin allowlists, no CORS, no-store,
  and restrictive CSP.

## Verification

The complete project gate passes (Ruff format, Ruff check, MyPy strict, and PyTest):

```bash
.venv/bin/ruff format --check src/ tests/
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src
.venv/bin/pytest
```

Result (2026-07-18, handoff checkpoint): 62 tests passing, 85.69% total
coverage. The real localhost smoke cycle starts, fetches all product endpoints,
stops, and cleans its synthetic repository. Browser review passes at 1440px
desktop and 390px mobile; the mobile document has no horizontal overflow,
keyboard skip/copy works, and the console reports zero errors or warnings. A
fresh wheel was installed into an isolated Python 3.11 environment; packaged
HTML/CSS/JS/favicon/demo assets were present and its demo smoke passed.

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
- Claude Code commonly records absolute file paths. `RecoveryBrief` v1 rejects
  them by design; a future adapter revision needs an explicitly reviewed
  normalization policy before real-session path comparison becomes convenient.
- Only `claude-code-jsonl@1` is implemented. Codex and Gemini adapters remain
  deferred until after the competition submission.

## Next Useful Work

- Record the public under-three-minute YouTube demo using
  `agent-ledger demo`, then review the Devpost preview. Submit only after
  explicit owner confirmation.
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
