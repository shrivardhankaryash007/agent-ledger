# ADR 0003 — Verified recovery separates transcript record from current proof

- Status: **Accepted** (owner-approved plan, 2026-07-17)
- Author: Codex (`coding_strong`)
- Extends: ADR 0002 and the M3 continuity surface

## Context

The existing `ResumePacket` v1 reconstructs a useful narrative handoff from a
Claude Code transcript. That is sufficient for M3 dogfood, but a competition
demo needs to make a stronger and narrower promise: show what the interrupted
session recorded, show what Git proves now, and never blur the two into causal
attribution.

Transcripts are private, provider-specific, and attacker-controlled from the
recovery process's perspective. They may contain shell commands, prompt
injection, stale TODOs, credentials, absolute paths, or an attempted test with
no corresponding result. The current repository is owner-selected and local,
but transcript-provided paths can still escape it if passed to the filesystem
or Git without validation.

## Decision

1. Introduce `RecoveryBrief` v1 as a new provider-neutral contract. Do not
   mutate `ResumePacket` v1. The source adapter has its own independent
   identity (`claude-code-jsonl@1`) so providers can evolve without changing
   the recovery schema.
2. Model three evidence classes separately:
   - recorded tool attempt;
   - recorded result status (`recorded`, explicit `error`, or `missing`);
   - repository state observed now relative to `HEAD`.
   A transcript never proves current state or causation.
3. Treat all transcript text and tool inputs as untrusted evidence. Bash
   command bodies and tool-result content do not enter the public model.
   Continuation actions come only from fixed application-authored templates;
   recovery never executes a recorded command.
4. Require an explicit trusted repository (`--repo`, defaulting only to the
   invocation working directory). Accept only normalized POSIX
   repository-relative transcript paths. Reject absolute paths, traversal,
   backslashes, leading-dash pathspec tricks, and symlink escapes before any
   per-path Git inspection.
5. Limit Git to fixed, read-only argument vectors and place `--` before every
   validated path. Do not reuse the narrative ending detector's
   transcript-provided `cwd` Git heuristic; recovery v1 reports ending as
   unknown until a repo-confined classifier is specified.
6. Serve the visual console only on `127.0.0.1`, behind an unguessable
   capability token, exact Host/Origin allowlists, no CORS, `no-store`, a
   restrictive Content Security Policy, and no external assets.
7. Ship the console as packaged HTML/CSS/JavaScript. The surface has one brief
   and one interaction, so a React/Node dependency would add install and demo
   failure modes without product leverage.
8. Make `agent-ledger demo` create a disposable synthetic Git repository and
   run the same assembler and API used for real recovery. `--smoke` must start,
   fetch, stop, and clean the server path.

## Why this over the alternatives

| Alternative | Why not |
|---|---|
| Extend `ResumePacket` in place | Conflates a narrative handoff with an evidence-linked trust contract and breaks existing consumers. |
| Copy transcript commands into next actions | Turns untrusted historical text into executable authority and makes missing tool results dangerously persuasive. |
| Infer success from a test invocation | An invocation without a paired result is exactly the interrupted-session ambiguity this product exists to surface. |
| Accept absolute paths under the trusted repo | More convenient for current Claude transcripts, but expands the parser's filesystem authority and makes containment reasoning harder to audit. A later adapter revision may add a separately reviewed normalization rule. |
| General network service | The product is a single-user local recovery surface. Remote access creates authentication, persistence, and privacy obligations outside this milestone. |
| React/Vite console | Adds a second toolchain and build step for a read-only surface whose state and interactions fit in dependency-free browser primitives. |

## Consequences

- The recovery JSON is deterministic for a fixed transcript, Git snapshot, and
  generation time; every claim references a known evidence ID.
- Real transcripts that record absolute file paths fail closed in v1. Users
  still receive non-path evidence only after a future reviewed adapter policy;
  v1 does not silently weaken the boundary for convenience.
- A paired non-error result is reported as recorded evidence, not proof that a
  test passed or that its effects remain in the worktree.
- The console remains useful without JavaScript build infrastructure and works
  from an installed wheel because all assets and the synthetic fixture are
  package resources.
- Provider adapters, automatic execution, background watchers, remote serving,
  and LLM-authored summaries remain explicitly deferred.

## Verification

The decision is enforced by path-escape tests, result-pairing tests, output
privacy tests, referential-integrity validation, API security tests, installed
asset checks, a real localhost smoke cycle, and desktop/mobile browser review.
