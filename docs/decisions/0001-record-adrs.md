# ADR 0001: Record architecture decisions

## Status

Accepted

## Context

Non-trivial architectural decisions need a durable, append-only record so
future sessions (any LLM, any tier) understand why the code looks the way it
does, per the workspace Coding Constitution §6.

## Decision

Every non-trivial architectural decision in this repo gets an ADR here:
context → decision → consequences → status. Append-only; superseded ADRs
link forward to the superseding one.

## Consequences

Slightly more upfront writing per decision; in exchange, no decision's
rationale is lost to chat history.
