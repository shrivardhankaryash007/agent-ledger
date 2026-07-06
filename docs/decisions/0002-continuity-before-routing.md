# ADR 0002 — The continuity surface (resume packet) precedes the routing/cost roadmap

- Status: **Accepted** (Fable session, 2026-07-06 — the "Session B" scope decision staged in `~/dev/EXECUTION-PLAN-fable-endgame.md`)
- Author: claude-fable-5 (frontier_deep)
- Supersedes: the milestone *sequencing* in `docs/architecture.md` as of 2026-07-06 (budget wallet as next milestone). Does **not** supersede the FS-2 decision (M2.5 "governable traffic exists" gate) — that gate stays, unchanged, in front of the budget wallet.

## TL;DR

**Yes — the next agent-ledger milestone is the resume-packet/continuity surface, before any further routing/cost work.** Confidence 78. The interruption trigger is the only CL2 trigger with observed founder evidence; the routing/cost path is currently blocked by two of its own preconditions (attribution kill fired at 57.8% < 80%; no governable traffic exists for the M2.5 soak); and the continuity surface reuses the transcript-ingest substrate M0 already built. Budget wallet renumbers to M4, still gated by M2.5. Nothing built in M0–M2 is discarded.

## A note on naming

The pre-staged prompt for this session asked whether "M1" should lead with continuity — written against the plan-of-record numbering, where M1 (live capture) had not yet shipped. In the repo, M0/M1/M2 are built and verified on real data (see `STATUS.md`). The decision therefore lands as the *next* milestone: **M3 — Resume Packet**, displacing the budget wallet to M4.

## Context

Four facts, all established before this session:

1. **The evidence asymmetry (wargame W8, 2026-07-06, confidence 80).** The mined corpus's one observed founder quote in the AI-dev cluster is "usage limits kill momentum" — an interruption/continuity pain, independently corroborated by the founder's memory corpus (usage-limits pain; ADHD context: *resumption* is the failure point). The spend/routing premise agent-ledger was scoped around has **no recorded acute founder complaint**. The wargame demoted the Usage-Limit Workflow (C19) to a module of agent-ledger (C08) and named this exact scope question as "the cluster's most decision-relevant open question."
2. **M0's attribution kill criterion fired and survived one rescope.** Per-project attribution on the real corpus is 57.8% call-weighted (threshold ≥80%). Per-project spend — the input every routing recommendation and per-agent budget depends on — is unreliable by construction today.
3. **M2.5 cannot start on its own.** No process in the workspace naturally routes traffic through the litellm capture point; IDE-seat traffic (the bulk of measured spend) goes direct to vendor APIs. The 5-day soak clock has no natural start event.
4. **The workspace handoff contract only covers graceful endings.** `HANDOFF-CONTRACT.md` v1.6.0 requires four session-end deliverables (STATUS update, session log, commit, next-work note) — all written *by the agent at session end*. A usage-limit interruption is precisely the ungraceful ending where none of them get written. The contract's prime directive ("the next agent resumes from filesystem and git alone") fails exactly at the moment the observed pain occurs. The wargame separately noted (W12) that the killed Cross-LLM Handoff Contract's mechanics "live on inside the resume-packet" — this ADR is where they land.

## Decision

1. **M3 — Resume Packet (continuity surface)** is the next milestone. Scope, acceptance criteria, iteration contract, and kill criterion in `EXECUTION-PLAN-m3-resume-packet.md`.
2. **M4 — Budget wallet** (formerly M3), unchanged in content, still gated behind M2.5 per FS-2.
3. **Attribution rescope #2** is demoted from "next useful work" to a **gated precondition of the routing/cost surfaces only** (M4 and any replay-derived recommendation claims). The resume packet operates per-session, not per-project-aggregate, and does not depend on crossing the 80% line.
4. **M2.5** remains a parallel, non-blocking observation. If Penny (or anything real) gets routed through the capture point, the soak runs as designed.
5. agent-ledger's identity widens from "cost ledger" to **session ledger**: spend and continuity are two read-surfaces over the same substrate (local transcripts + local event store). Public naming/positioning is a ship-window question, deliberately not decided here.

## Why this over the alternatives

| Alternative | Why not |
| --- | --- |
| **A. Proceed to M2.5 → M4 wallet as planned** | Builds enforcement on two known-broken preconditions: attribution below its own kill line, and soak traffic that doesn't exist. It also deepens investment in the spend thesis, which has zero observed founder evidence, while the observed pain (interruption) stays unserved. This is the sunk-cost path the wargame's evidence-hygiene section warned about. |
| **B. Attribution rescope #2 first** | Fixes the *input* to surfaces whose *trigger* is unevidenced. Sequencing repair-work in front of evidence-work optimizes the wrong variable. Rescope #2 becomes worth doing when (and only when) a routing/budget surface is actually next. |
| **C. Resume packet as a separate tool/repo** | Violates W8's strongest cluster finding (confidence 90): one buyer, one channel, one install surface — two products would compete for one founder and one channel. C19 was explicitly demoted to module_of C08. It also duplicates M0's transcript parser. |
| **D (chosen). Continuity milestone inside agent-ledger** | Targets the only observed trigger; reuses the already-built, already-kill-tested transcript ingest; leaves every routing/cost asset (M1 capture, M2 replay, the $295.12 ceiling number — which is total-spend/model-tier and unaffected by the attribution failure) intact and resumable when evidence or traffic arrives. |

## What this decision is *not*

- **Not a market claim.** Founder dogfood on continuity is stronger signal than on spend (he is the observed pain-holder), but per W8 it remains usability signal, not market evidence. The cluster's decisive external test is unchanged: external users importing their own data unaided.
- **Not a new product.** No new repo, no new channel, no public repositioning yet.
- **Not a kill of the routing thesis.** M1/M2 machinery stands; M4 wallet stays on the roadmap behind its existing gates.

## Consequences and named risks

1. **Platform absorption (highest external risk).** Claude Code ships native compaction/resume and will improve it. Mitigation: the packet is **cross-vendor by design** (Claude Code transcripts first, Codex/Gemini sources behind the same `CallRecordSource`-style plugin seam) and writes to the vendor-neutral handoff-contract schema. Single-vendor resume is the vendor's roadmap; *cross-vendor* resume of a multi-LLM workspace is structurally not, and multi-LLM operation is this workspace's documented reality.
2. **Meta-system trap.** The founder's own pattern review says friction decides adoption. Mitigation is structural: the packet is generated on demand from artifacts that already exist (transcripts, git) — zero capture discipline required at interruption time — and the milestone kill criterion is **behavioral and retrieval-based**, not generation-based (see plan §Kill).
3. **Privacy boundary inherited and extended.** Transcripts contain private data. AGENTS.md rule 3 (no cloud calls in ingestion) extends to the resume module: any LLM enrichment is local-ollama only, structurally.
4. **Fable-session cadence.** The next gate review (FS-2 trigger already fired via M0-kill + this rescope) is the M3 dogfood verdict: packet retrieved and used, or kill fires.

## Flip conditions

Reverse or revisit this sequencing if any of: (a) real governable traffic materializes and the M2.5 soak produces routing data with live decisions attached; (b) the M3 kill criterion fires (packets generated but not retrieved at real interruptions); (c) any vendor ships credible cross-vendor session resume.
