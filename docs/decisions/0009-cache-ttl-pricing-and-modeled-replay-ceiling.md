# 0009 — Price Claude cache writes by TTL; limit replay savings to modeled calls

- **Status:** Accepted
- **Date:** 2026-10-29
- **Supersedes:** none
- **Amends:** M2 replay reporting and M0 Claude transcript cost calculation; no core record or schema changes

## Context

The replay result already tracked `not_modeled_cost_usd`, but `ceiling_savings_usd` subtracted only downgraded cost from all actual spend. This contradicted the CLI label that excluded unsupported calls from the ceiling.

Claude usage provides both aggregate `cache_creation_input_tokens` and a `cache_creation` breakdown with 5-minute and 1-hour TTL token counts. Ingestion previously retained only the aggregate and priced every write at the existing 5-minute rate. Anthropic's current pricing documentation lists 5-minute writes at 1.25x and 1-hour writes at 2x the effective input rate, while cache-read rates include per-model exceptions.

## Decision

1. Define replay ceiling savings as `actual_cost_usd - not_modeled_cost_usd - downgraded_cost_usd`, so only modeled calls contribute. Calls without an approved downgrade mapping remain visible in their separate spend/call fields.
2. Keep `CallRecord.cache_write_tokens` as the aggregate already represented by the frozen schema. Add an optional keyword-only `cache_write_1h_tokens` subset to `cost_usd`; its cost is 2x the effective input rate returned by `_rates_for_prompt`. Remaining writes use the existing per-SKU cache-write rate. Invalid 1-hour counts outside the aggregate subset fail with `ValueError`.
3. During Claude transcript ingestion, aggregate `cache_creation.ephemeral_1h_input_tokens` in a local bucket and pass that subset to `cost_usd`. Do not add TTL fields to `CallRecord`, `Price`, `pricing.yaml`, or SQLite. The persistent record keeps aggregate cache-write tokens plus the corrected total cost.
4. Leave Anthropic cache-read rates, including SKU-specific exceptions, unchanged. Long-prompt pricing remains selected by `_rates_for_prompt`; the 1-hour write rate is twice that selected input rate.
5. Do not rewrite collected rows or run a backfill. A historical cost correction requires a separately reviewed, deliberate re-ingest/replay.

## Evidence

- Official Anthropic [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) usage shape: top-level cache-write total equals the nested 5m and 1h TTL counters.
- Official Anthropic [Pricing](https://platform.claude.com/docs/en/about-claude/pricing): 1-hour cache writes cost 2x base input; model-specific cache-read pricing remains separate.
- Tests prove modeled-only replay arithmetic, all-unmodeled zero ceiling, mixed TTL write pricing, long-prompt rate selection, invalid TTL subset rejection, and transcript ingestion without changing stored token shape.

## Consequences

- New transcript ingests price 1-hour cache writes accurately while exposing only the existing aggregate cache-write token field.
- Existing records retain their existing `cost_usd` until an owner authorizes a separate audited re-ingest.
- The M2 ceiling no longer counts spend for calls whose downgrade is not modeled. It remains a theoretical upper bound, not a quality-aware routing recommendation.
