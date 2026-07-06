# Execution Packet: M0-rescope — attribute calls by per-line `cwd`, not transcript-folder name

- Author (thinking model / tier): claude-code (Sonnet 5, reasoning_strong)
- Executor target (tier): codex / coding_strong
- Date: 2026-07-06

## 0. Author pre-flight
- [x] The expected diff touches EXACTLY ONE file: `src/agent_ledger/ingest/claude_transcripts.py`.
- [x] That file already exists with correct imports/exports in place.
- [x] A check exists that is RED now and turns GREEN only when done:
      `tests/test_m0_cwd_attribution.py` (new file, already written, already
      run — confirmed FAIL: `assert written == 2` got `1`).
- [x] Every contract is pasted verbatim below.
- [x] "Done" is fully defined by §4 passing plus the existing
      `tests/test_m0_ingest_report.py` continuing to pass unchanged (no
      regression on the no-`cwd` fixture path).

## Context (why this exists)

The M0 kill criterion ("<80% of calls attributable to a project → stop and
rescope") fired against the real transcript corpus on 2026-07-06: only
11.6% attribution, because `path.parent.name` reflects the directory Claude
Code was started from, and almost every session here starts from the
workspace root (`~/dev`). Real transcript inspection (not guessed) found
that each JSONL line independently carries a `cwd` field that *does* track
the actual working directory at that message — and that it changes
mid-session when a root-started session later touches a specific project
subdirectory (confirmed against a real transcript file: same `sessionId`,
lines with `cwd` alternating between `/Users/yashshrivardhankar/dev` and
`/Users/yashshrivardhankar/dev/careledger`). Full reasoning in
`STATUS.md`'s Current Baseline / Next Useful Work sections.

## 1. The ONE file you may edit
`src/agent_ledger/ingest/claude_transcripts.py`

You may NOT create, rename, move, or edit any other file — see §6.

## 2. The task
Make the failing test in §4 pass by changing how `parse_transcript` buckets
transcript lines and derives each resulting `CallRecord.project`.

## 3. Contract — verbatim, do not infer

Current relevant code (for reference, to be changed):

```python
buckets: dict[str, Bucket] = {}
for raw_line in text.splitlines():
    ...
    session_id = str(record.get("sessionId") or path.stem)
    bucket = buckets.setdefault(model, Bucket(session_id=session_id))
    bucket.in_tokens += _token_count(usage.get("input_tokens"))
    ...

...
for model, bucket in buckets.items():
    ...
    records.append(
        CallRecord(
            ...,
            project=path.parent.name,
            ...
        )
    )
```

Required new behavior:

1. Each top-level JSON `record` (one JSONL line) may carry a top-level
   string field `record.get("cwd")` (sibling of `sessionId`/`timestamp`/
   `message` — NOT nested inside `message`). It may be absent, `None`, or
   an empty string; treat all of those as "no cwd for this line."
2. Bucket key changes from `model` alone to `(model, project_for_line)`,
   where `project_for_line` is computed **per line**, before bucket lookup:
   - If the line's `cwd` is a non-empty string: `project_for_line =
     Path(cwd).name` (the last path segment — e.g.
     `/Users/yashshrivardhankar/dev/careledger` → `"careledger"`,
     `/Users/yashshrivardhankar/dev` → `"dev"`).
   - Else: `project_for_line = path.parent.name` (the existing fallback,
     unchanged — this is what keeps `test_m0_ingest_report.py`'s no-`cwd`
     fixture passing exactly as today).
3. `Bucket` (the dataclass) gains a `project: str` field (or you may key the
   `buckets` dict by the `(model, project)` tuple directly and read the
   project back out of the key when constructing records — either is fine,
   pick whichever keeps the diff smaller).
4. When constructing each `CallRecord`, set `project=<the bucket's own
   project>` instead of the current blanket `project=path.parent.name`.
5. Every other field/behavior (pricing lookup, capability classification,
   timestamp fallback, `session_id` derivation, the `ValueError` on missing
   pricing) is unchanged.

`CallRecord` model (frozen, for reference only — do not edit
`ledger/models.py`):
```python
class CallRecord(BaseModel):
    model_version: int = MODEL_VERSION
    ts: datetime
    session_id: str
    project: str
    model_sku: str
    capability_class: str
    vendor: str
    in_tokens: NonNegativeInt
    out_tokens: NonNegativeInt
    cost_usd: float = Field(ge=0.0)
    calls: NonNegativeInt
```

## 4. Acceptance — you are done when this prints PASS
```bash
uv run pytest tests/test_m0_cwd_attribution.py tests/test_m0_ingest_report.py -v
```
`test_m0_cwd_attribution.py` FAILs now (`assert written == 2` gets `1`)
because `parse_transcript` buckets by `model` alone and always sets
`project=path.parent.name`, so the 3-line mixed-`cwd` fixture collapses into
one record under `-Users-yashshrivardhankar-dev` instead of splitting into
`dev` (1 call) and `careledger` (2 calls). `test_m0_ingest_report.py` must
keep passing unchanged — it has no `cwd` field in its fixture at all, so it
exercises the fallback path.

Make the first test print PASS, and keep the second at PASS, by editing only
`src/agent_ledger/ingest/claude_transcripts.py`.

## 5. Closed verify loop
```bash
uv run pytest tests/test_m0_cwd_attribution.py tests/test_m0_ingest_report.py -v
uv run mypy src
uv run ruff check .
uv run ruff format --check .
```

## 6. Forbidden — hard stops
- Editing any file other than the one named in §1 — not the test, not
  either fixture, and not the ledger model file (the `CallRecord` model is
  frozen per AGENTS.md rule 1; this task does not require touching it).
- Modifying either test file or either fixture.
- Adding or upgrading any dependency.
- Re-running the real M0 ingest against `~/.claude/projects` and reporting a
  new attribution percentage is OUT OF SCOPE for this packet — that is a
  separate owner-facing step after this lands, not part of "done" here.
- If the task cannot be done within these limits: STOP, write ONE line
  saying why, and change nothing.

## 7. Gate before commit — frontier or human ONLY, never the executor
- [ ] Full project gate: `uv run ruff check .`, `uv run ruff format --check .`,
      `uv run mypy src`, `uv run pytest` (whole suite, not just the two files
      above — coverage floor is 80% on touched modules per AGENTS.md rule 4).
- [ ] A frontier model or human reads the actual diff before committing.
- [ ] Per ADR 0028: commit this session's own work, write the session log,
      update `STATUS.md`'s Current Baseline / Next Useful Work to record that
      the rescope landed (owner still decides separately whether to re-run
      the real ingest and re-check the 80% threshold — that's the next step
      after this, not part of this packet).
