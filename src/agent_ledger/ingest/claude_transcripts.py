"""M0 ingest source: Claude Code JSONL transcripts.

Reads `<source_dir>/<project-dir>/*.jsonl` (rglob), one directory per
project (the directory name IS the project — Claude Code names it from the
sanitized cwd). This is the one gap found in the existing workspace ledger
(`~/dev/scripts/ide_meter.py` parses the same files but discards the parent
directory name); this module captures it as `CallRecord.project`.

Independent of `~/dev/scripts/token_ledger.py` / `ide_meter.py` by design —
see AGENTS.md rule 2. Parse/classify logic may be *read* from those files as
reference; this module must not import or modify them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.pricing import cost_usd, load_pricing
from agent_ledger.ledger.repository import migrate, upsert

SYNTHETIC_MODEL = "<synthetic>"


@dataclass
class Bucket:
    """Aggregated usage for one model within a transcript."""

    session_id: str
    project: str
    in_tokens: int = 0
    out_tokens: int = 0
    calls: int = 0
    last_ts: str = ""


@dataclass
class TranscriptLineStats:
    """Counters describing lines skipped while iterating a transcript."""

    skipped_lines: int = 0


def _timestamp(raw: str, path: Path) -> datetime:
    """Parse a transcript timestamp, falling back to the file modification time."""

    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _token_count(value: object) -> int:
    """Return a JSON token count, treating absent or malformed values as zero."""

    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def classify(model: str) -> tuple[str, str]:
    """Map a transcript model id to ``(capability_class, vendor)``."""

    name = model.lower()
    if "opus" in name or "fable" in name:
        return "frontier_deep", "anthropic"
    if "sonnet" in name:
        return "coding_strong", "anthropic"
    if "haiku" in name:
        return "fast_small", "anthropic"
    if "codex" in name:
        return "coding_strong", "openai"
    if name.startswith("gpt"):
        return "frontier_deep", "openai"
    if "gemini" in name:
        return "frontier_deep", "google"
    if "grok" in name:
        return "frontier_deep", "xai"
    return "frontier_deep", "other"


def iter_transcript_lines(
    path: Path, stats: TranscriptLineStats | None = None
) -> Iterator[dict[object, object]]:
    """Yield parsed JSON dictionaries, counting malformed lines when requested.

    Args:
        path: Local transcript JSONL path.
        stats: Optional mutable counters for skipped malformed lines.

    Yields:
        Parsed JSON objects that are dictionaries.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            decoded: object = json.loads(line)
        except json.JSONDecodeError:
            if stats is not None:
                stats.skipped_lines += 1
            continue
        if not isinstance(decoded, dict):
            if stats is not None:
                stats.skipped_lines += 1
            continue
        yield cast("dict[object, object]", decoded)


def parse_transcript(path: Path) -> list[CallRecord]:
    """Aggregate one transcript into per-model records with project context."""

    buckets: dict[tuple[str, str], Bucket] = {}
    for record in iter_transcript_lines(path):
        message_value = record.get("message")
        if not isinstance(message_value, dict):
            continue
        message = cast("dict[object, object]", message_value)
        model = message.get("model")
        usage_value = message.get("usage")
        if (
            not isinstance(model, str)
            or not model
            or model == SYNTHETIC_MODEL
            or not isinstance(usage_value, dict)
        ):
            continue
        usage = cast("dict[object, object]", usage_value)
        session_id = str(record.get("sessionId") or path.stem)

        cwd = record.get("cwd")
        if isinstance(cwd, str) and cwd:
            project_for_line = Path(cwd).name
            bucket_session_id = f"{session_id}:{project_for_line}"
        else:
            project_for_line = path.parent.name
            bucket_session_id = session_id

        bucket = buckets.setdefault(
            (model, project_for_line),
            Bucket(session_id=bucket_session_id, project=project_for_line),
        )
        bucket.in_tokens += _token_count(usage.get("input_tokens"))
        bucket.in_tokens += _token_count(usage.get("cache_creation_input_tokens"))
        bucket.out_tokens += _token_count(usage.get("output_tokens"))
        bucket.calls += 1
        timestamp = str(record.get("timestamp") or "")
        if timestamp > bucket.last_ts:
            bucket.last_ts = timestamp

    prices = load_pricing()
    records: list[CallRecord] = []
    for (model, _project), bucket in buckets.items():
        if model not in prices:
            raise ValueError(f"no pricing configured for transcript model {model!r}")
        capability_class, vendor = classify(model)
        records.append(
            CallRecord(
                ts=_timestamp(bucket.last_ts, path),
                session_id=bucket.session_id,
                project=bucket.project,
                model_sku=model,
                capability_class=capability_class,
                vendor=vendor,
                in_tokens=bucket.in_tokens,
                out_tokens=bucket.out_tokens,
                cost_usd=cost_usd(model, bucket.in_tokens, bucket.out_tokens, prices),
                calls=bucket.calls,
            )
        )
    return records


def ingest(source_dir: Path, db_path: Path) -> int:
    """Scan ``source_dir`` and idempotently upsert every parsed record."""

    migrate(db_path)
    written = 0
    for path in sorted(source_dir.rglob("*.jsonl")):
        for record in parse_transcript(path):
            upsert(db_path, record)
            written += 1
    return written
