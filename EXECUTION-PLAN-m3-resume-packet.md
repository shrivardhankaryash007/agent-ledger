# Execution Plan: M3 — Resume Packet (continuity surface)

- Author (thinking model / tier): claude-fable-5 (frontier_deep), 2026-07-06
- Decision record: `docs/decisions/0002-continuity-before-routing.md` (read it first — it is the "why"; this file is the "what/how")
- Executor: Codex (coding_strong) builds from per-diff packets cut from this plan by Sonnet; local qwen for boilerplate only, supervised. Fable returns only at the M3 gate verdict.
- Effort: ≤5 evenings build (M3.a + M3.b), then a 14-day passive dogfood window (M3.c). Hard stop: if build exceeds 8 evenings, stop and raise a Desk blocker.
- Recommended handoff seat for packet-cutting: Sonnet, HIGH effort (per workspace handoff doctrine).

## Product statement

When a Claude Code (later: Codex/Gemini) session dies mid-work — usage limit, crash, abandon — no session log gets written and the handoff contract's four deliverables never happen. `agent-ledger resume` reconstructs the missing handoff **after the fact, from artifacts that already exist** (the session transcript + git state): what was being attempted, what was touched, where it stopped, and what the next three actions are. Output is a markdown **resume packet** in the exact `HANDOFF-CONTRACT.md` session-log schema, so any vendor's next session can pick up from the filesystem alone.

Zero capture discipline is required at interruption time — that is the design's load-bearing property. If the packet ever requires the dying session to have done something first, the design has failed.

## Architecture (locked stack, §3/§5 of the constitution)

New module `src/agent_ledger/resume/` — read-only surface over the same transcript substrate M0 ingests. It writes nothing to the ledger DB in M3 (no repository interaction, core stays frozen).

```
src/agent_ledger/resume/
  models.py     # ResumePacket (pydantic v2), SessionEnding enum, PACKET_VERSION = 1
  detector.py   # session-ending classification over parsed transcript lines
  extractor.py  # deterministic field extraction (intent, touched files, last state)
  render.py     # markdown render, HANDOFF-CONTRACT session-log schema
```

- CLI (typer, existing app): `agent-ledger resume [--session ID] [--project NAME] [--out PATH]` and `agent-ledger resume --list` (session table with ending classification). Default with no args: most recent non-`completed` session.
- **Shared parsing seam:** transcript-line iteration/parsing lives in `ingest/claude_transcripts.py`. If `resume/` needs access, expose a public function there (e.g. `iter_transcript_lines(path) -> Iterator[dict]`) and consume it — do NOT copy the parser and do NOT touch `ledger/` core. This refactor, if needed, is its own packet with the existing M0 tests as the regression net.
- Git enrichment: `git -C <cwd> status --porcelain` via subprocess when the session's last `cwd` is known and is a repo; every failure path degrades to `git_status: unavailable`, never an exception.
- **Privacy (hard rule, extends AGENTS.md rule 3):** transcripts are private data. The `resume/` module makes **no cloud calls, ever**. The optional M3.c LLM enrichment is local ollama only, structurally (no litellm route that can reach a cloud provider).
- Port: none. M3 is CLI-only. A later Desk endpoint uses the registered 8680.

### ResumePacket model (v1 — versioned from day 1)

`packet_version, generated_at, session_id, project, provider, model_skus, started, last_activity, ending, in_tokens, out_tokens, intent, touched_files, bash_commands, last_state, git_status, next_actions, source_path`

`SessionEnding ∈ {completed, interrupted_limit, interrupted_abort, unknown}`.

## Milestones

### M3.a — Corpus recon + ending detector (1–2 evenings)

**First task is looking, not coding:** inspect real transcripts under `~/.claude/projects/` and document — in `docs/resume-endings.md` — what an ending actually looks like per class (limit-error lines? truncated tool_use? absence of closing turns?). Do not guess markers; the M0-rescope packet's "real transcript inspection, not guessed" discipline applies. Then implement `detector.py` against those documented markers, with synthetic fixtures per class (real transcripts are private — never committed).

*Acceptance (executor-verifiable):* unit tests green for each ending class on synthetic fixtures; `agent-ledger resume --list` renders a classification table over the real corpus without error; markers documented.
*Acceptance (owner gate, not executor):* founder spot-checks 10 sessions classified `interrupted_*` — ≥8/10 judged correct. Recorded in STATUS.
*Engineering fallback (not a kill):* if limit-interruptions leave no distinguishable trace, `unknown` + most-recent-session default is acceptable; record the finding — it weakens `--list` but not the surface.

### M3.b — Packet generator + render (2–3 evenings)

Deterministic extraction: first user message → intent; `Edit`/`Write`/`NotebookEdit` tool_use → touched files; `Bash` tool_use → command list; final assistant text + any in-flight todo state → last_state; heuristic next-actions from unfinished todo items / last stated plan. Render to the handoff session-log schema with a resume header.

*Acceptance:* golden-file regression test on a synthetic fixture session; end-to-end run against the real most-recent session produces a packet with every mandatory section non-empty (recorded in STATUS, packet itself not committed); full project gate green.

### M3.c — Dogfood + optional local enrichment (14-day passive window)

Optional `--llm` flag: local-ollama summarization of last_state/next_actions (better prose, same facts). One-line dogfood log per real interruption: date, packet generated? packet used to resume?

*Acceptance:* ≥3 real interruptions in the window where the packet was generated **and used** (used = the next session started from the packet's next-actions).

## Kill criterion (milestone-level, behavioral)

Within the 14-day dogfood window: if ≥3 real interruptions occur and the founder resumes **without using the packet** in ≥⅔ of them, the continuity surface has lost to the manual contract and memory. Then: demote `resume` to the `--list` session table only, close M3 as failed-but-informative, and put the routing roadmap (attribution rescope #2 → M2.5 → M4) back on the table at the next Fable gate. Retrieval is the test — generation volume proves nothing (a packet nobody reads is a graveyard).

## Iteration contract

- `PACKET_VERSION` field from v1; any schema change bumps it and keeps the renderer able to render v1 models (test enforced).
- `ledger/` core untouched; `resume/` is removable without breaking anything (agent-proof seam).
- Gates per packet close: `mypy --strict`, `ruff check` + `format --check`, ≥80% coverage on touched modules, golden-file regression on rendered packets, hypothesis property test: the extractor never raises on arbitrary/malformed JSONL lines (skips and counts them).
- Every packet cut from this plan follows the EXECUTION-PACKET-m0 pattern: one file, red test first, verbatim contracts, forbidden list.

## Sequencing of the rest of the roadmap (from ADR 0002)

| Slot | Content | Gate |
| --- | --- | --- |
| M3 | Resume packet (this plan) | dogfood kill above |
| M2.5 | Governable-traffic soak | parallel, non-blocking; starts if/when real traffic is routed |
| Attribution rescope #2 | second strategy for the 42.2% workspace-root bucket | precondition of M4 only |
| M4 | Budget wallet (former M3, unchanged) | M2.5 + rescope #2 |

## Shipping window

M3 is not a public ship by itself. It creates the ship-window story ("a usage limit killed my session mid-refactor; my ledger wrote the handoff packet"): after M3.c passes, a Ship Log post draft is the next owner-triggered artifact, per the existing plan's owner-triggered ship window and the visibility constraint (GitHub + Ship Log; LinkedIn held).
