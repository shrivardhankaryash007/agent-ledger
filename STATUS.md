# agent-ledger Status

Last updated: 2026-07-05

## Current Baseline

- M0 repository, Claude transcript ingestion, local pricing, and per-project
  spend aggregation are implemented.
- Repository writes are idempotent on `(session_id, model_sku)` and reject an
  unsupported schema version.
- Transcript records retain `path.parent.name` as their project attribution.
- The fixture-backed M0 acceptance test passes; no real private transcript
  corpus was ingested during this implementation session.

## Verification

The complete project gate passes:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Result: 20 tests passed; total branch coverage is 91.60% (80% required).

## Dirty / In-Flight State

- The M0 implementation, focused tests, and this handoff update belong to the
  session-end commit required by ADR 0028.
- No pre-existing dirty paths were present when the session started.

## Known Gaps

- M0 has not yet been exercised against the private live transcript corpus;
  models absent from `ledger/pricing.yaml` fail explicitly to prevent silent
  zero-cost records.
- M1 live capture, M2 counterfactual replay, and M3 budget enforcement remain
  deferred per `docs/architecture.md`.

## Next Useful Work

- Run the M0 CLI against the local Claude transcript directory and check the
  real attribution ratio before starting M1. If attribution is below 80%, stop
  and rescope attribution as required by the M0 kill criterion.
