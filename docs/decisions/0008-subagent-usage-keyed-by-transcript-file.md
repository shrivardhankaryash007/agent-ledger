# 0008 — Subagent usage keyed by its transcript file, not overwriting the parent

- **Status:** Accepted (2026-10-08)
- **Date:** 2026-10-08
- **Supersedes:** none
- **Amends:** the row key `session_id` for Claude Code **subagent** transcripts only; `MODEL_VERSION` stays 4 (see Consequences)
- **Follows up:** ADR 0007, follow-up #1 (row-key collision drops spend)

## TL;DR

Claude Code writes a subagent's transcript to `<project>/<session>/subagents/agent-<id>.jsonl`, and every line in it carries the **parent's** `sessionId`. The bucket key was `<sessionId>:<tag>`, and `upsert` is `ON CONFLICT (session_id, model_sku) DO UPDATE`, which **replaces**. So a subagent's usage overwrote the parent's row instead of adding to it. About $121 (26% of Claude Code spend in the 2026-10-02 measurement) never reached the ledger.

**Decision:** a transcript under a `subagents/` directory gets the key suffix `:subagent:<file stem>`. Ordinary transcripts get no suffix, so their keys and rows do not change. No schema, `CallRecord`, or repository change.

## Context

Facts, measured or read from code:

| Fact | Source |
|---|---|
| Subagent lines carry the parent's `sessionId` | ADR 0007 follow-up #1; `tests/test_subagent_sessions.py` |
| `upsert` replaces on `(session_id, model_sku)` | `ledger/repository.py`, `ON CONFLICT ... DO UPDATE` |
| Last file written wins per key | Follows from the two facts above |
| $121.27 (26%) lost across 5 keys | ADR 0007, follow-up #1 |
| 35 of 192 transcripts are subagent files | ADR 0007, corpus snapshot 2026-10-02 |
| Subagent files are not duplicates of main-file lines | ADR 0007 (none of 145 cross-file duplicate ids involve a subagent file) |

Why the parent row is "last file wins": before this change, `parse_transcript` built the same `session_id` for every file of one session, so whichever file was ingested last set the value for each `(session_id, model_sku)` key.

## Decision

1. **Suffix subagent rows with their file stem.** `_session_suffix(path)` returns `:subagent:<stem>` when `path.parent.name == "subagents"`, else `""`. The bucket key becomes `<sessionId>:<tag><suffix>`.
2. **Ordinary sessions are byte-identical.** Same `session_id`, same values. Rows already in the ledger are not re-keyed, which satisfies collected-data rule 1 in `AGENTS.md`.
3. **Parent and subagent rows are distinct by construction**, because the stem `agent-<id>` is unique within a session and the parent key has no suffix.
4. **Re-ingest stays idempotent.** The suffix is a pure function of the file path, so re-ingesting upserts the same keys with the same values.
5. **No change to `CallRecord`, the repository API, or the SQLite schema.** The fix is contained in `parse_transcript`'s key computation.

### Why this over the alternatives

| Alternative | Why rejected |
|---|---|
| **Key subagent rows by transcript file (chosen)** | Smallest change that makes keys distinct. Touches only subagent files, whose rows are the ones being lost. Parent rows keep their meaning. |
| **Sum at upsert** (change `ON CONFLICT` to add) | Breaks idempotency: re-ingesting the same transcript would add it again. Changes the repository API's semantics, which rule 1 freezes. |
| **Add a column** (`source_file` or `is_subagent`) to the primary key | Changes `PRIMARY KEY (session_id, model_sku)`, so it needs a migration and a version bump. The packet forbids a schema change, and the file-stem suffix gives the same distinctness without one. Revisit if reports need to query subagent spend without string parsing. |
| **Re-key every transcript by file stem** | Re-keys ordinary sessions, orphaning every existing row (violates must-hold 3). Also changes how resumed sessions aggregate. |
| **Group files by `sessionId` and sum before upsert** | Makes a parent row's value depend on which other files are present in the same run. That changes the meaning of existing parent rows, which rule 1 forbids without a version bump. |
| **Skip subagent files** | Drops $128.6 of real, billed subagent spend (ADR 0007 rejected this for the same reason). |
| **Key by an agent id read from the line** | Not chosen because I did not verify that real lines carry a per-agent identifier. The file stem is the only identifier this code relies on. |

## Consequences

- **Parent and ordinary rows are unchanged on their own.** Subagent rows are added beside them. Totals for a session become parent + subagents, which is what must-hold 1 requires.
- **Measured on the real corpus before landing** (copies of `data/ledger.db`, read-only on `~/.claude/projects`, 2026-10-08): the old code ingesting today's transcripts gave 495 rows / $2,598.74; the new code on the same input gave 530 rows / $2,727.36. The difference, +$128.62, equals the 36 subagent rows ($128.63) to the cent, so no spend is double-counted. The hazard this ADR first drafted (an old row under a parent key that the parent file never regenerates, because only a subagent produced that `(model, label)` bucket) exists in principle but did not occur in this corpus. A normal re-ingest, which the nightly launchd job already does, recovers the missing spend; no backfill script is needed.
- **If that hazard ever appears** (a later corpus with a subagent-only bucket whose old row survives): list parent-key rows whose `(session, model)` also has a `:subagent:` row, check each against its transcripts, and delete the stale ones on a copy of the database first.
- **`MODEL_VERSION` stays 4.** The stored figures keep their meaning: tokens, calls and cost are computed exactly as before; only the row key for subagent files changed. Rows whose transcripts no longer exist were never recoverable and a bump would not make them so (unlike ADR 0007, where the figures themselves changed meaning).
- **`SCHEMA_VERSION` stays 3.** No column is added, removed, or retyped, so `migrate()` has nothing to do.
- **Per-file de-duplication (ADR 0007) is unchanged.** Subagent files are not duplicates of main-file lines, so per-file dedup remains correct for them. The cross-file duplicate issue (ADR 0007 follow-up #2) is still open and is not addressed here.
- **Residual risk:** if a future subagent file replayed parent history, its responses would be counted under the suffixed key and so double-counted. ADR 0007 measured no such case in the current corpus.

## Verification

- `tests/test_subagent_sessions.py` (5 tests): totals equal parent plus subagent, re-ingest changes nothing, an ordinary session keeps its key, parent and subagent rows differ, this ADR exists. Written red first; the full suite (136 tests), `mypy --strict`, `ruff check` and `ruff format --check` pass.
- The corpus measurement above.
- Drafted by Claude Haiku 5.5 from a planner packet; reviewed, corrected (status, the hazard analysis, verification) and measured by the planner.
