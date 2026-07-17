# OpenAI Build Week — Verified Recovery Console

## Product claim

When a coding agent dies, Agent Ledger separates what the session recorded
from what the repository proves now, then hands the next agent a safe local
continuation brief.

This extension is deliberately not an AI summary. It is a deterministic
recovery instrument built from two local evidence sources: a provider
transcript and the owner-selected Git worktree.

## Run the judge path

```bash
uv sync
uv run agent-ledger demo
```

The browser opens a capability-protected console on
`http://127.0.0.1:8680`. The demo creates a disposable repository, commits a
`before` state, writes an uncommitted `after` state, and supplies a synthetic
interrupted transcript. That transcript records a verification command
invocation but no tool result.

The expected result is exact:

- the session recorded an edit attempt and a Bash attempt;
- `src/check.py` currently differs from `HEAD`;
- verification is **unknown**, never inferred as pass;
- the next agent is told to inspect, verify from current project instructions,
  and reconcile before continuing;
- the recovered command body never appears in JSON, prompt, or console;
- stopping the server removes the disposable demo directory.

For a non-interactive installation check:

```bash
uv run agent-ledger demo --no-open --smoke --port 0
```

## Recover a real local session

```bash
uv run agent-ledger recover \
  --session <SESSION_ID> \
  --repo /absolute/path/to/trusted/repository \
  --format json

uv run agent-ledger recover \
  --session <SESSION_ID> \
  --repo /absolute/path/to/trusted/repository \
  --format prompt

uv run agent-ledger recover \
  --session <SESSION_ID> \
  --repo /absolute/path/to/trusted/repository \
  --open
```

`AGENT_LEDGER_CLAUDE_PROJECTS_DIR` can redirect transcript discovery from the
default local Claude Code directory. Transcript processing remains entirely
local and makes no cloud or model calls.

## Trust model

| Input | Authority |
|---|---|
| Owner-selected repository | Trusted root for read-only inspection |
| Transcript envelope and tool IDs | Untrusted historical evidence |
| Transcript commands, outputs, TODOs, prose | Never executable authority |
| Application action templates | The only source of continuation actions |
| Current Git snapshot | Present-tense observation, not causal proof |

The localhost console requires a random capability token and rejects unknown
Host and Origin headers. It sends no CORS permissions, stores no cacheable
responses, allows no external assets, and disables framing through both CSP
and `X-Frame-Options`.

## Competition provenance

- Implementation session: Codex task
  `019f6ef5-6285-7e73-b10f-d6776a436285`.
- Core product code is new work performed during the Build Week window.
- No private transcript content or credentials are committed. Tests and the
  demo use synthetic records only.
- The existing ledger and resume packet remain intact; this is a versioned
  extension with a separate trust contract.

## Deferred after submission

- Codex and Gemini transcript adapters;
- absolute-path normalization policy for provider transcripts;
- automatic command execution;
- remote or multi-user serving;
- background worktree watchers;
- LLM-authored recovery summaries.
