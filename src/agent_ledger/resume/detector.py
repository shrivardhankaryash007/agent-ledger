"""Session ending classification logic over parsed transcript lines."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent_ledger.ingest.claude_transcripts import iter_transcript_lines
from agent_ledger.resume.models import SessionEnding

if TYPE_CHECKING:
    from pathlib import Path


def parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO 8601 timestamp string.

    Guarantees a timezone-aware UTC datetime.
    """

    if ts_str.endswith("Z"):
        ts_str = ts_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _has_matching_git_commit(cwd_path: str, last_activity_time: datetime) -> bool:
    """Check if a git commit exists within window.

    Window: [-10 mins, +15 mins] of last_activity_time.
    """

    try:
        since_time = int(last_activity_time.timestamp()) - 600
        until_time = int(last_activity_time.timestamp()) + 900

        cmd = [
            "git",
            "-C",
            cwd_path,
            "log",
            f"--since={since_time}",
            f"--until={until_time}",
            "--format=%at",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        timestamps = res.stdout.strip().splitlines()
        for ts_str in timestamps:
            if ts_str.isdigit():
                ts = int(ts_str)
                if since_time <= ts <= until_time:
                    return True
    except Exception:
        # degrade gracefully
        pass
    return False


def detect_ending(transcript_path: Path) -> SessionEnding:
    """Detect whether a session ended gracefully or ungracefully."""

    try:
        lines = list(iter_transcript_lines(transcript_path))
    except Exception:
        return SessionEnding.unknown

    if not lines:
        return SessionEnding.unknown

    # Extract end time
    end_ts_str = ""
    for record in reversed(lines):
        if "timestamp" in record and isinstance(record["timestamp"], str):
            end_ts_str = record["timestamp"]
            break

    if not end_ts_str:
        return SessionEnding.unknown

    try:
        last_activity = parse_timestamp(end_ts_str)
    except Exception:
        return SessionEnding.unknown

    # Find the latest CWD
    cwd = None
    for record in reversed(lines):
        if "cwd" in record and isinstance(record["cwd"], str):
            cwd = record["cwd"]
            break

    # Look at the tail (last 5 lines)
    tail = lines[-5:]

    # Check for rate/usage limit errors (highest precedence)
    for record in tail:
        if record.get("apiErrorStatus") == 429 or record.get("apiErrorStatus") == "429":
            return SessionEnding.interrupted_limit

        error_val = record.get("error")
        if error_val:
            error_str = str(error_val).lower()
            if any(
                w in error_str
                for w in [
                    "rate_limit",
                    "quota_exceeded",
                    "max_tokens_exceeded",
                    "usage_limit",
                    "rate limit",
                    "quota exceeded",
                    "usage limit",
                ]
            ):
                return SessionEnding.interrupted_limit

        if record.get("isApiErrorMessage") is True:
            record_str = str(record).lower()
            if any(
                w in record_str
                for w in [
                    "rate_limit",
                    "quota_exceeded",
                    "max_tokens_exceeded",
                    "usage_limit",
                    "rate limit",
                    "quota exceeded",
                    "usage limit",
                ]
            ):
                return SessionEnding.interrupted_limit

    # Check for abort/network/connection errors in tail
    for record in tail:
        error_val = record.get("error")
        if error_val:
            error_str = str(error_val).lower()
            if any(
                w in error_str
                for w in [
                    "econnreset",
                    "connectionrefused",
                    "failedtoopensocket",
                    "connection error",
                ]
            ):
                return SessionEnding.interrupted_abort

        if record.get("isApiErrorMessage") is True or "apiErrorStatus" in record:
            return SessionEnding.interrupted_abort

    # Check if last line is a graceful ending
    last_record = lines[-1]
    last_type = last_record.get("type")

    is_graceful = False
    if (
        last_type == "mode"
        and last_record.get("mode") == "normal"
        or last_type in ("ai-title", "last-prompt")
    ):
        is_graceful = True

    if is_graceful:
        return SessionEnding.completed

    # If not graceful, check git commits
    if cwd and _has_matching_git_commit(cwd, last_activity):
        return SessionEnding.completed

    return SessionEnding.interrupted_abort
