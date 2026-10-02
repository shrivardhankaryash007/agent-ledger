"""M0 ingest source: Claude Code JSONL transcripts.

Reads `<source_dir>/<project-dir>/*.jsonl` (rglob). Each line's `cwd` field
is resolved to a repo identity via `ingest.git_label.resolve` (fix spec
2026-08-02, docs/decisions/0005-attribution-keys-on-git-identity.md) —
*not* a directory basename. The old basename convention (Claude Code's own
sanitized-cwd project-dir naming, and this module's original
`path.parent.name` fallback) is what produced 86% unusable labels on the
real corpus: launch directory, not working repo. `source_dir`'s per-project
directory layout is still how transcripts are discovered on disk; it plays
no part in attribution anymore.

Usage de-duplication (ADR 0007): Claude Code writes one API response as
several JSONL lines — one per content block — that share `message.id` and
repeat the response's `usage`. A response is therefore counted **once**, from
its *last* line (the first line holds a partial streaming `output_tokens`).
Consequently `CallRecord.calls` means "API responses", not "transcript lines".
Lines with no `message.id` cannot be merged safely and are each counted.
De-duplication is per transcript file; the same response can still appear in
two files (a resumed or forked session replays history) — see ADR 0007.

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

from agent_ledger.ingest.git_label import GitLabel, resolve
from agent_ledger.ledger.models import CallRecord, LabelSource
from agent_ledger.ledger.pricing import cost_usd, load_pricing
from agent_ledger.ledger.repository import migrate, upsert

SYNTHETIC_MODEL = "<synthetic>"
UNKNOWN_PROJECT = "unknown"


@dataclass
class Bucket:
    """Aggregated usage for one model within a transcript."""

    session_id: str
    project: str
    repo_name: str | None
    worktree_name: str | None
    branch: str | None
    label_source: LabelSource
    cwd_raw: str | None = None
    in_tokens: int = 0
    out_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0  # distinct API responses (message.id), not transcript lines
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


@dataclass
class _UsageLine:
    """One API response's usage, as read from its last transcript line."""

    model: str
    usage: dict[object, object]
    session_id: str
    cwd_raw: str | None
    timestamp: str


def _usage_lines(path: Path) -> list[_UsageLine]:
    """Return one `_UsageLine` per API response in ``path``, in first-seen order.

    Lines sharing a `message.id` collapse to the **last** such line, whose
    `usage` is final; a later line also replaces the model/cwd of an earlier
    one. The surviving timestamp is the latest across the merged lines, so a
    row's `ts` is unchanged by de-duplication. Lines without a usable
    `message.id` are kept individually.
    """

    entries: list[_UsageLine] = []
    index_by_id: dict[str, int] = {}
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
        cwd_value = record.get("cwd")
        entry = _UsageLine(
            model=model,
            usage=cast("dict[object, object]", usage_value),
            session_id=str(record.get("sessionId") or path.stem),
            cwd_raw=cwd_value if isinstance(cwd_value, str) and cwd_value else None,
            timestamp=str(record.get("timestamp") or ""),
        )
        message_id = message.get("id")
        if not isinstance(message_id, str) or not message_id:
            entries.append(entry)
            continue
        seen_at = index_by_id.get(message_id)
        if seen_at is None:
            index_by_id[message_id] = len(entries)
            entries.append(entry)
            continue
        entry.timestamp = max(entry.timestamp, entries[seen_at].timestamp)
        entries[seen_at] = entry
    return entries


def _bucket_tag(label: GitLabel) -> str:
    """Short human string identifying a bucket's attribution, for session_id
    disambiguation only — never stored as ``project`` directly."""

    if label.label_source != "git" or not label.repo_name:
        return UNKNOWN_PROJECT
    if label.worktree_name:
        return f"{label.repo_name}-{label.worktree_name}"
    return label.repo_name


def parse_transcript(
    path: Path, *, git_cache: dict[str, GitLabel] | None = None
) -> list[CallRecord]:
    """Aggregate one transcript into per-model records with git-resolved
    attribution, counting each API response (`message.id`) once.

    Args:
        path: Transcript JSONL file.
        git_cache: Optional cwd -> GitLabel memo shared across an `ingest()`
            run — most consecutive lines in a session share one cwd, and
            each resolution costs three `git` subprocess calls, so reusing
            results across files matters at real transcript volume.

    Returns:
        One `CallRecord` per (model, repo, worktree, label) bucket. `calls`
        is the number of distinct API responses in the bucket.

    Raises:
        ValueError: A transcript model has no configured pricing.

    Example:
        Three content-block lines of one response yield ``calls == 1`` and the
        usage of the last line, not three times it.
    """

    cache: dict[str, GitLabel] = git_cache if git_cache is not None else {}

    def resolve_cached(cwd: str | None) -> GitLabel:
        if not cwd:
            return resolve(None)
        cached = cache.get(cwd)
        if cached is None:
            cached = resolve(cwd)
            cache[cwd] = cached
        return cached

    buckets: dict[tuple[str, str | None, str | None, LabelSource], Bucket] = {}
    for line in _usage_lines(path):
        model, usage, session_id, cwd_raw = (
            line.model,
            line.usage,
            line.session_id,
            line.cwd_raw,
        )
        label = resolve_cached(cwd_raw)

        project = label.repo_name if label.label_source == "git" else None
        project = project or UNKNOWN_PROJECT
        bucket_session_id = f"{session_id}:{_bucket_tag(label)}"

        key = (model, label.repo_name, label.worktree_name, label.label_source)
        bucket = buckets.setdefault(
            key,
            Bucket(
                session_id=bucket_session_id,
                project=project,
                repo_name=label.repo_name,
                worktree_name=label.worktree_name,
                branch=label.branch,
                label_source=label.label_source,
            ),
        )
        if cwd_raw:
            bucket.cwd_raw = cwd_raw
        # `cache_read_input_tokens` was dropped entirely before v3. On a
        # harness that re-sends a large cached prefix on every call it is the
        # dominant stream, so both volume and cost were understated without
        # any signal that they were. It is tracked as its own field rather
        # than folded into `in_tokens`, which must keep its v1/v2 meaning.
        cache_write_tokens = _token_count(usage.get("cache_creation_input_tokens"))
        bucket.in_tokens += _token_count(usage.get("input_tokens"))
        bucket.in_tokens += cache_write_tokens
        bucket.cache_write_tokens += cache_write_tokens
        bucket.cache_read_tokens += _token_count(usage.get("cache_read_input_tokens"))
        bucket.out_tokens += _token_count(usage.get("output_tokens"))
        bucket.calls += 1
        if line.timestamp > bucket.last_ts:
            bucket.last_ts = line.timestamp

    prices = load_pricing()
    records: list[CallRecord] = []
    for (model, *_key), bucket in buckets.items():
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
                cache_read_tokens=bucket.cache_read_tokens,
                cache_write_tokens=bucket.cache_write_tokens,
                cost_usd=cost_usd(
                    model,
                    bucket.in_tokens,
                    bucket.out_tokens,
                    prices,
                    cache_read_tokens=bucket.cache_read_tokens,
                    cache_write_tokens=bucket.cache_write_tokens,
                ),
                calls=bucket.calls,
                repo_name=bucket.repo_name,
                worktree_name=bucket.worktree_name,
                branch=bucket.branch,
                cwd_raw=bucket.cwd_raw,
                label_source=bucket.label_source,
            )
        )
    return records


def ingest(source_dir: Path, db_path: Path) -> int:
    """Scan ``source_dir`` and idempotently upsert every parsed record."""

    migrate(db_path)
    git_cache: dict[str, GitLabel] = {}
    written = 0
    for path in sorted(source_dir.rglob("*.jsonl")):
        for record in parse_transcript(path, git_cache=git_cache):
            upsert(db_path, record)
            written += 1
    return written
