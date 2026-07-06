# Session Ending Signatures and Classifications

This document outlines how `agent-ledger resume` classifies the ending of a session by looking at the trailing lines of its transcript and correlating with git commit timestamps.

## Session Ending Classes

### 1. `completed` (Graceful Ending)
The session completed successfully and the CLI exited gracefully.
- **Graceful Transcript Endings**: The last line of the transcript is an event of type `mode` (with `"mode": "normal"`), `ai-title`, or `last-prompt`.
- **Git Correlation**: If the transcript doesn't end with a graceful type but a git commit is found in the session's last active repository directory (`cwd`) within a `[-10 minutes, +15 minutes]` window of the last transcript activity timestamp, the session is classified as `completed` (assuming the user completed and committed from their terminal).
- **Precedence**: This classification has lower precedence than `interrupted_limit`. If a rate limit error exists in the tail, it is always `interrupted_limit`.

### 2. `interrupted_limit` (Rate/Usage Limit)
The session was terminated because it hit an API rate limit, quota limit, or token usage limit.
- **Markers (last 5 lines)**:
  - `apiErrorStatus == 429` (integer or string)
  - `error == "rate_limit"` or `"quota_exceeded"`
  - `error` dict/string contains substring `"rate limit"`, `"quota exceeded"`, `"usage limit"`, or `"max_tokens_exceeded"`.
  - `isApiErrorMessage == true` with similar error details.

### 3. `interrupted_abort` (Abort or Crash)
The session was aborted by the user (Ctrl+C, socket drop) or crashed mid-execution.
- **Markers**:
  - The tail contains network/connection errors (e.g. `ECONNRESET`, `ConnectionRefused`, `FailedToOpenSocket`).
  - Or, the transcript last line is NOT a graceful type (e.g. it is `assistant`, `user`, or `tool_use`), and NO git commit is found in the repository within the `[-10 minutes, +15 minutes]` window.

### 4. `unknown`
The session has no recognizable patterns.
- **Markers**:
  - Empty file.
  - Parsing errors (corrupt JSONL).
  - No lines with timestamps are present in the transcript.
