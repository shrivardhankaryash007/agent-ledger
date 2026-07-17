# agent-ledger Status

Last updated: 2026-07-18 (Recovery Loop v1 plan verified and awaiting owner approval; no source implementation started)

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
- **Recovery Loop v1 is planned, not implemented** (2026-07-18):
  `plans/recovery-loop-v1/` defines a repository-bound Claude Code + Codex
  Recovery Inbox, safe absolute-path reconciliation, content-sensitive command
  receipts, and a canonical recovery package. The plan, wireframes, and
  prototype pass the local Agent-Native schema/bridge checks. A skeptical
  review's false-green findings were incorporated; source changes remain paused
  at the approval gate.

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
  them by design; Recovery Loop v1 now has a reviewed containment policy, but
  that policy is not implemented yet.
- Only `claude-code-jsonl@1` is implemented. Codex and Gemini adapters remain
  absent. Recovery Loop v1 scopes Codex next; Gemini remains deferred.

## Next Useful Work

- Review and approve `plans/recovery-loop-v1/`; after approval, implement Packet
  1 by writing the failing Codex call-pairing, repository-binding, and absolute
  path-containment tests before source changes. The public demo video, M3.c
  passive dogfood, attribution rescope, and Penny capture integration remain
  deferred behind this explicit approval gate.
