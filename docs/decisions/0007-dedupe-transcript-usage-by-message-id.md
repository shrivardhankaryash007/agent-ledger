# 0007 — Count each API response once: de-duplicate transcript usage by `message.id`

- **Status:** Accepted — owner directed it be landed (2026-10-02); merged to local `main`, production DB re-ingested, not pushed
- **Date:** 2026-10-02
- **Supersedes:** none
- **Amends:** the meaning of `CallRecord.calls` and of every stored token/cost
  figure sourced from Claude Code transcripts (`MODEL_VERSION` 3 → 4)

## TL;DR

`parse_transcript` summed `message.usage` over every transcript **line**. Claude
Code writes one API response as several lines (one per content block) that share
a `message.id` and repeat its `usage`. Cost was overstated **2.22x** on the full
corpus (2.13–2.36x in every month). The parser now keeps one entry per
`message.id`, **last line wins**. `MODEL_VERSION` becomes 4 so corrected rows are
distinguishable from rows that can never be corrected. No column changes, so no
schema migration.

## Context

Measured read-only on the full local corpus (`~/.claude/projects`, snapshot
2026-10-02: 192 transcripts, 35 of them subagent files):

| | Line-sum (v3 behaviour) | De-duplicated by `message.id` | Ratio |
|---|---|---|---|
| Usage lines / responses | 12,988 | 6,164 | 2.11 lines per response |
| Output tokens | 10,715,434 | 4,249,724 | 2.52x |
| Cache-read tokens | 2.457 B | 1.184 B | 2.08x |
| Cost (current pricing table) | $1,013.62 | $456.31 | **2.22x** |

By month (ratio of line-sum cost to de-duplicated cost): 2026-07 **2.13x**,
2026-08 **2.19x**, 2026-09 **2.20x**, 2026-10 **2.36x**. Older transcripts repeat
lines exactly as new ones do, so this is not a recent regression; it has been in
the parser since M0. Distribution of lines per response: 1 → 1,412; 2 → 3,187;
3 → 1,210; 4 → 279; up to 13.

The ratio matches the symptom that exposed it: STATUS.md recorded `$1,596.36`
on 2026-08-02, ADR 0006 then moved the total to `$2,570.83` by adding cache
tokens, and the live ledger stood at `$2,923.71` on 2026-10-02 — each step
rested on a per-line sum.

Within one `message.id` the `usage` is identical across lines **except
`output_tokens`**, which grows as the response streams (94 of 6,164 responses
differ; no other field ever did). Last-wins equals max-per-field on the whole
corpus; first-wins understates output by 2.0% (4,166,819 vs 4,249,724).

## Decision

1. **De-duplicate by `message.id`, last line wins**, inside `parse_transcript`
   (new helper `_usage_lines`). The surviving entry's timestamp is the latest
   across the merged lines, so a row's `ts` is unchanged.
2. **Lines with no `message.id` are each counted**, exactly as before. They
   cannot be merged safely, and no real transcript line lacked an id (0 of
   12,988), so this only protects fixtures and foreign sources.
3. **`calls` now means "distinct API responses"**, not "transcript lines".
   Documented on `CallRecord`, `Bucket`, and the module docstring. `litellm`
   (M1) already writes `calls=1` per request and is unaffected.
4. **`MODEL_VERSION` 3 → 4; `SCHEMA_VERSION` stays 3.** No column is added,
   removed or retyped, so there is nothing for `migrate()` to do and a v3
   database opens unchanged. The version bump is the AGENTS.md rule 1 marker:
   `model_version < 4` now means *summed per line, overstated ~2.2x, not
   re-derivable if the source transcript is gone*.
5. **Re-ingest is the backfill**, as in ADR 0006 — idempotent upsert on
   `(session_id, model_sku)`. No bespoke script, and **no historical row is
   scaled or rewritten by a heuristic**.

### Why this over the alternatives

| Alternative | Why rejected |
|---|---|
| First line wins | Understates output tokens: the first line is the streaming snapshot at block start. −2.0% output on the real corpus. |
| `max(usage)` per field | Same numbers today, but a heuristic that silently breaks if a field ever legitimately decreases; "last line" is the documented final state. A test pins last-wins as positional. |
| Skip `isSidechain: true` lines/files | Would drop **$128.6 of real, billed subagent spend** (all 35 subagent files). Subagent responses are not duplicates of main-file lines: none of the 145 cross-file duplicate ids involves a subagent file. Rejected as a correctness error, not a style choice. |
| Divide historical rows by the measured ~2.2x | Fabricates precision. The ratio varies by month (2.13–2.36x) and by session shape, and v1/v2 rows are *also* cache-blind (opposite error). Stored numbers must stay measured. |
| Bump `SCHEMA_VERSION` too (ADR 0006 precedent) | ADR 0006 added columns; this adds none. Bumping would make an otherwise-identical schema reject by older code for no gain. Revisit if a column (e.g. `dedup_basis`) is ever added. |
| Do nothing to `MODEL_VERSION` | Corrected and uncorrectable rows would both read `3` — a silent mix of two definitions of `calls`/cost, the exact failure rule 1 exists to prevent. |

## Consequences

- **Recorded total on a copy of `data/ledger.db` (production untouched):**

  | | Rows | Cost |
  |---|---|---|
  | Live DB as recorded 2026-10-02 21:51 | 433 | $2,923.71 |
  | Old code re-ingested on the same corpus snapshot | 436 | $2,931.17 |
  | **New code re-ingested on the same snapshot** | 436 | **$2,499.33** |

  Change vs old code on identical input: **−$431.84 (−14.7%)**.
- **Like-for-like on the 126 rows that re-ingest can reach:** $768.98 → $337.14
  (**2.28x**), calls 8,516 → 3,962, output tokens 10.70 M → 4.19 M.
- **Why the headline moves only 14.7%:** 310 rows ($2,162.20) have no surviving
  source transcript (the on-disk corpus starts 2026-07-14; the DB starts
  2026-04-22; why older files are gone was not investigated) and cannot be corrected. By version: v1 155 rows
  $858.91, v2 19 rows $97.65, v3 136 rows $1,205.64. They stay as recorded.
  The v3 rows alone are probably ~$500–575 of real spend (÷ the measured
  2.1–2.4x; an estimate, not stored). The v1/v2 rows have two opposing errors
  (overcounted per-line sums, but no cache tokens) and are **not** estimated.
- **Reports must treat `model_version < 4` as an upper bound for Claude Code
  spend.** Not yet implemented (see follow-ups).
- `report/spend.py` and `policy/replay.py` need no code change; the M2
  counterfactual ceiling (`$295.12` of `$544.18`) was computed on the inflated
  base and should be re-run before it is quoted again.
- **Landed 2026-10-02:** live `data/ledger.db` (backup kept beside it) re-ingested by the same command launchd runs: 433 rows $2,923.71 → 443 rows $2,504.79 (v4: 133 rows $342.59; stale v1-v3: 310 rows $2,162.20). A repeat run drifted +$0.10 only because the running session's own transcript was still growing.
- Re-ingest idempotency verified on the copy: three consecutive runs produced
  identical row counts, totals and a hash over every stored row.

## Follow-ups found while measuring (not fixed here — separate decisions)

| # | Finding | Size | Why not folded in |
|---|---|---|---|
| 1 | **Row-key collision silently drops spend.** Subagent transcripts carry the *parent's* `sessionId`, so several files yield the same `(session_id, model_sku)` and `upsert` overwrites — last file wins, no addition. | After this fix: $458.40 produced, $337.14 stored → **$121.27 (26%) lost** across 5 keys | Changes row identity (the primary key); needs its own ADR and a migration plan. It is now the largest remaining error in the Claude Code path, and it errs low. |
| 2 | **Cross-file duplicate responses.** 145 `message.id`s appear in two non-subagent files with different `sessionId`s (resumed/forked sessions replay history). Per-file de-dup cannot see them. | $10.39 (2.3%) | Needs a corpus-wide pass in `ingest()`, interacts with #1. |
| 3 | Reports do not yet surface `model_version < 4` as unverified. | — | Presentation change, own packet. |

## Verification

- Red-first: `tests/test_m4_message_dedup.py` — 6 of 8 failed against the old
  parser for the stated reason (`calls == 2`, per-line sums); the 2 that passed
  are the intentional back-compat guards (no-id lines, `ts` unchanged).
  Includes a `hypothesis` property: repeating any line any number of times never
  changes the result.
- Gates: `pytest` 115 passed (86% total coverage, 99% on
  `ingest/claude_transcripts.py`), `mypy --strict` clean, `ruff check` and
  `ruff format --check` clean.
- Corpus measurement and re-ingest were run on a frozen snapshot of
  `~/.claude/projects` and a copy of `data/ledger.db`; the live DB was not opened
  for writing (size and mtime unchanged).
