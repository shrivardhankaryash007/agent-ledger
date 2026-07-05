# Contributing

Solo-build, public-ready. No external PRs expected, but the bar is kept as if
there were reviewers.

- Read `AGENTS.md` before touching code.
- Every change: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).
- Non-trivial architectural decisions get an ADR in `docs/decisions/`.
