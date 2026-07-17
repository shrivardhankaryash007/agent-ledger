# Recovery evidence contract

This note records the local, structural reconnaissance behind the
`claude-code-jsonl@1` recovery adapter. No transcript content, command text,
tool output, credentials, or private filesystem paths were copied into this
repository.

## Observed envelope

Claude Code transcripts are newline-delimited JSON records. Tool invocations
appear as `tool_use` blocks inside an assistant message's `content` list. Tool
results appear as `tool_result` blocks inside a user message's `content` list.

| Signal | Observed shape | Recovery interpretation |
|---|---|---|
| Tool identity | `tool_use.id`, a string with a `toolu_` prefix | Stable pairing key within the transcript |
| Tool kind | `tool_use.name` | Recorded attempt category only |
| Tool input | `tool_use.input`, an object | Untrusted evidence; command bodies are never promoted to actions |
| Result pairing | `tool_result.tool_use_id` | Joins a result to the recorded attempt |
| Result content | String or array | Evidence that a result was recorded; not copied into the brief |
| Explicit failure | `tool_result.is_error: true` | Recorded error |
| Non-error result | `is_error: false` or the field is absent | Recorded result, with no explicit error signal |
| Missing result | No matching `tool_result` | Outcome unknown; never inferred as success |

## Adapter rules

1. Pair results only by exact `tool_use.id` / `tool_use_id` equality.
2. Mark a paired result `error` only when `is_error` is explicitly `true`.
3. Mark any other paired result `recorded`; this does not prove the repository
   still has the state the tool produced.
4. Mark an unpaired invocation `missing`.
5. Preserve tool name, line number, and a digestable locator as evidence.
   Discard Bash command bodies and tool-result content from the public recovery
   model.
6. Extract file paths only from the known file-touching tool fields. Validate
   every path against the owner-supplied repository before filesystem or Git
   access.
7. Treat user, assistant, TODO, command, and tool-result text as untrusted
   evidence. Only application-authored continuation templates may appear in
   `continuation_actions`.

## Why this over transcript narration

A transcript can show that an agent attempted a command and that the provider
recorded a result. It cannot, by itself, prove the current worktree, prove that
an omitted result succeeded, or establish that the recorded action caused the
current repository state. Recovery therefore keeps three claims separate:

- recorded attempt;
- recorded result status;
- repository state observed now relative to `HEAD`.

That separation is the product's trust boundary, not presentation copy.
