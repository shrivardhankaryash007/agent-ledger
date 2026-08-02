# 0006 — Cache tokens are first-class ledger fields

- **Status:** Accepted
- **Date:** 2026-08-02
- **Supersedes:** none
- **Amends:** the `CallRecord` shape frozen by AGENTS.md rule 1 (v2 → v3)

## Context

`ingest.claude_transcripts.parse_transcript` summed `input_tokens` and
`cache_creation_input_tokens` into `in_tokens` and **never read
`cache_read_input_tokens` at all**. On a harness that re-sends a large cached
prefix on every call, cache reads are the dominant token stream, so the ledger
was blind to most of its own subject matter.

The symptom that exposed it: an average of 8,447 `in_tokens` per call across
21,802 calls — implausibly low for real Claude Code sessions, and low in a way
that looked like healthy efficiency rather than a measurement hole.

Two consequences:

1. **`cost_usd` was understated**, silently, with no signal that it was. The
   ledger's entire purpose is cost truth; it was reporting a floor as a total.
2. **The share of spend attributable to always-loaded context could not be
   computed at all** — the question the ledger exists to answer.

## Decision

Bump `MODEL_VERSION` / `SCHEMA_VERSION` to 3 and add two additive fields,
`cache_read_tokens` and `cache_write_tokens`, both `NOT NULL DEFAULT 0`.

**`in_tokens` keeps its v1/v2 meaning — fresh input plus cache writes.** It is
not redefined. `cache_write_tokens` is therefore a deliberately *redundant*
breakdown of part of `in_tokens`, while `cache_read_tokens` is genuinely new
volume that `in_tokens` never contained.

The alternative — redefining `in_tokens` as fresh input only — was rejected.
It produces a cleaner model going forward but silently changes what the column
means across the version boundary, so any historical row whose transcript no
longer exists would be mixed into new rows under a different definition with no
way to tell them apart. AGENTS.md rule 1 exists to prevent exactly that.

Pricing gains optional per-SKU `cache_read` / `cache_write` rates, defaulting to
Anthropic's published multipliers against the base input rate (0.1x read,
1.25x write) when omitted — so cache accounting did not require re-stating
rates for every already-priced historical SKU. `cost_usd` re-rates cache writes
*out of* the base input rate rather than adding them, so passing them can never
double-charge.

Migration is cumulative: a v1 database gains the v2 attribution columns and the
v3 cache columns in one `migrate()` call.

## Consequences

- **The recorded total moved from $1,599.28 to $2,570.83** after re-ingest — a
  previously invisible $971 (61%). This is still a floor: rows whose source
  transcript no longer exists keep `0`, meaning "not measured", not "no cache".
- Cache reads are **96.4% of token volume** on measured rows (2.22B read vs
  189M fresh+write), at ~179k cache-read tokens per call. Any future analysis
  that reasons about token volume without this field is wrong by ~28x.
- `cost_usd(...)` gained keyword-only cache arguments defaulting to `0`, which
  reproduces the exact pre-v3 result. M1 live capture keeps working unchanged
  and simply keeps reporting a cache-blind number until it is updated — a known,
  bounded gap rather than a silent one.
- Re-ingest is the backfill mechanism. It is idempotent (upsert on
  `(session_id, model_sku)`), so correctness is restored wherever the source
  transcript survives, without a bespoke migration script.
- **Open:** `project = 'unknown'` still covers a meaningful share of spend where
  `cwd` was absent or not a git repo. Cache accounting does not address it.
