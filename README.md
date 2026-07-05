# agent-ledger

Local-first LLM cost and routing ledger for a solo, agent-heavy dev workflow.
Ingests every recorded LLM call, attributes real cost per project, and (later
milestones) replays calls against a routing policy to quantify savings and
enforce per-agent token budgets.

## What it is

- A SQLite-backed ledger that turns local Claude Code (and later, other IDE
  seat) transcripts into a per-project spend table.
- Single-user, single-machine. No server-side multi-tenant ambitions.

## What it is NOT

- Not a cloud observability dashboard (Helicone/Langfuse-class tools already
  do that well). The wedge is local-first interception plus opinionated
  routing recommendation/enforcement, not another chart.
- Not a proxy or gateway for LLM traffic in M0 — M0 is batch ingestion of
  existing transcripts only.
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
```

## Design principles

See `~/dev/standards/coding-constitution/CODING-CONSTITUTION.md` (this repo
inherits it) and `AGENTS.md` for project-specific overrides. Module
boundaries and the M0-M3 milestone plan live in `docs/architecture.md`.

## License

MIT — see `LICENSE`.
