# agent-ledger Status

Last updated: 2026-07-18 (Recovery Loop v1 Packet 1 implemented and verified)

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
- **Recovery Loop v1 Packet 1 is implemented and verified** (2026-07-18,
  ADR 0004): the provider-neutral adapter seam supports declared Claude Code
  and Codex JSONL formats, Codex calls pair with outputs only by exact call ID,
  discovery binds candidates to the exact trusted Git root, and contained
  absolute paths normalize safely. Raw call arguments and output bodies do not
  enter public evidence models. Packets 2-4 remain to be implemented.

## Verification

The complete project gate passes (Ruff format, Ruff check, MyPy strict, and PyTest):

```bash
.venv/bin/ruff format --check src/ tests/
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src
.venv/bin/pytest
```

Result (2026-07-18, Packet 1 checkpoint): 70 tests passing, 86.15% total
coverage; Ruff format/check and MyPy strict also pass. Structure-only dogfood
against the real recovered Codex rollout found 277 tool attempts, 276 matched
outputs, and one unmatched attempt; the adapter classified it as interrupted
and discovered it only within the trusted repository boundary. The real
localhost smoke cycle starts, fetches all product endpoints,
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
- The Recovery Loop browser still opens one preassembled brief; the planned
  immutable multi-provider Inbox and lazy selected-session assembly are not yet
  connected to the API or UI.
- Command receipts, content-sensitive freshness, and the canonical recovery
  package are not yet implemented. Gemini remains deliberately deferred.

## Next Useful Work

- Implement Recovery Loop v1 Packet 2 test-first: change the localhost console
  from one preassembled brief to an immutable repository-bound candidate Inbox,
  preserve the existing single-brief compatibility path, and add lazy
  digest-checked selected-session assembly. The public demo video, M3.c passive
  dogfood, attribution rescope, and Penny capture integration remain deferred.
