# ADR 0004 — Recovery Loop adapters, repository binding, and command authority

- Status: **Accepted** (owner-approved 2026-07-18)
- Author: Codex (`general_strong`)
- Extends: ADR 0003

## Context

ADR 0003 established a single-provider, single-brief console that separates
recorded transcript activity from current Git proof. Real recovery is still
awkward: Codex has a different event envelope, Claude commonly records absolute
paths, a session can be accidentally compared with the wrong repository, and a
recorded tool result is not current verification.

The Recovery Loop must become more convenient without granting transcript text
or a localhost browser authority to select repositories or run commands. It
must also avoid false-green freshness when repository content changes without a
different porcelain status code.

## Decision

1. Provider support is an explicit versioned adapter protocol. Discovery emits
   redacted `SessionCandidate` metadata; extraction emits normalized structural
   `TranscriptEvidence`. Results pair only by exact provider call ID. Unknown
   shapes fail closed.
2. A repository-scoped catalog includes a candidate only when its recorded cwd
   canonically resolves to the exact owner-selected Git root. Project names and
   transcript-supplied repository choices are never binding evidence.
3. Recorded relative and absolute paths are untrusted. An absolute path is
   converted to repository-relative form only after canonical containment is
   proven. Traversal, option-like paths, backslashes, sibling worktrees, and
   symlink escapes fail before per-path Git inspection.
4. The browser remains capability-protected and GET-only. It cannot select an
   arbitrary filesystem path, launch a process, or mutate repository state.
5. The only command-execution door is an explicit CLI argv supplied by the
   owner after `--`. Transcript text never enters argv. Execution is shell-free,
   has no stdin, runs in the trusted repository, and uses bounded process-group
   timeout handling.
6. A command receipt records only an observed process outcome. Owner labels are
   untrusted annotation. Raw argv, environment, stdout, and stderr are not
   persisted by default, so the package is not independently reproducible.
7. Receipt freshness uses a content-sensitive repository fingerprint covering
   HEAD, staged diff, tracked worktree diff, and untracked content. Snapshot
   inability is non-current. The latest attempt governs; an older exited-zero
   attempt never masks a later failure, error, timeout, or stale result.
8. Recovery packages are canonical JSON with component checksums, not signed
   attestations. Checksum consistency does not claim attacker-resistant
   integrity.

## Consequences

- Claude and Codex can share one recovery contract without heuristic parser
  reuse.
- Some sessions are deliberately excluded when cwd evidence is missing or
  cannot be bound to the selected repository.
- Repository-contained absolute paths become usable while escape cases remain
  fail-closed.
- Verification remains an explicit owner action outside the browser. A receipt
  can say `command exited 0`; it cannot say what the command semantically proved.
- Content-sensitive fingerprints cost more than porcelain inspection and may
  return unavailable for bounded-resource or special-file cases.
- Adding a provider, web execution, receipt signing, or remote collaboration
  requires a new reviewed adapter or authority decision.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Reuse the Claude parser for Codex | Event envelopes and result pairing differ; silent reuse would invent evidence. |
| Bind by project/repository name | Names collide and are transcript-controlled; canonical Git-root equality is the trust boundary. |
| Continue rejecting all absolute paths | Safe but unnecessarily excludes common real Claude evidence that can be proven inside the selected root. |
| Run verification from the browser | Turns the capability URL into a command-execution surface. |
| Hash only `git status --porcelain` | Misses content changes that preserve the same status letters. |
| Call exit code zero “tests passed” | The process outcome does not establish the semantic meaning of arbitrary argv or owner labels. |

## Verification

Packet 1 proves adapter pairing, candidate binding, privacy, and path
containment. Packet 3 must prove process-group execution boundaries,
content-sensitive drift, latest-attempt precedence, checksum limitations, and
privacy before receipts can be surfaced as current.
