# agent-ledger

Local-first session ledger for a solo, agent-heavy dev workflow. It measures
recorded model usage and recovers interrupted coding sessions without turning
transcript narration into current truth.

## What it is

- A SQLite-backed ledger that turns local Claude Code (and later, other IDE
  seat) transcripts into a per-project spend table.
- A verified recovery console that separates recorded tool attempts from the
  repository state Git proves now.
- Single-user, single-machine. No server-side multi-tenant ambitions.

## What it is NOT

- Not a cloud observability dashboard (Helicone/Langfuse-class tools already
  do that well). The wedge is local-first interception plus opinionated
  routing recommendation/enforcement, not another chart.
- Not a proxy or gateway for LLM traffic in M0 — M0 is batch ingestion of
  existing transcripts only.
- Not an autonomous resumption agent. Recovered commands are never executed or
  promoted into continuation actions.
- Not a replacement for `~/dev/scripts/token_ledger.py` — that ledger keeps
  recording workspace-wide JSONL as-is. agent-ledger ingests from the same
  raw Claude Code transcript source independently and adds project
  attribution; the two are not meant to merge in M0.

## Stack

| Layer | Tool |
|---|---|
| Language | Python 3.11+ |
| Package mgr | `uv` |
| Data frames | `polars` |
| Storage | SQLite (stdlib `sqlite3`) |
| API | FastAPI (read-only, Desk widget consumer) |
| CLI | `typer` |
| Config | `pydantic` v2 + `pydantic-settings` |
| Logging | `structlog` |
| Tests | `pytest` + `hypothesis` |
| Lint/types | `ruff`, `mypy --strict` |

## Quickstart

```bash
uv sync
uv run pytest
uv run agent-ledger ingest ~/.claude/projects
uv run agent-ledger report
uv run agent-ledger demo
```

The demo opens a secure local recovery console with a disposable synthetic
interruption. For a headless installation check, run:

```bash
uv run agent-ledger demo --no-open --smoke --port 0
```

## OpenAI Build Week

The Build Week extension focuses on continuity for interrupted coding agents.
`agent-ledger recover` emits a versioned evidence brief or safe continuation
prompt, while `agent-ledger demo` opens the Verified Recovery Console. The
implementation session is Codex task
`019f6ef5-6285-7e73-b10f-d6776a436285`; earlier M3 packet work is task
`019f5f12-2a4a-7b43-a3a4-15ea1ec2a203`.

This repository deliberately keeps raw coding transcripts local. The public
code and tests use no private transcripts or credentials.

See `docs/buildweek-extension.md` for the exact judge path, trust model, and
real-session commands.

## Design principles

See `~/dev/standards/coding-constitution/CODING-CONSTITUTION.md` (this repo
inherits it) and `AGENTS.md` for project-specific overrides. Module
boundaries and the M0-M3 milestone plan live in `docs/architecture.md`.

## License

MIT — see `LICENSE`.
