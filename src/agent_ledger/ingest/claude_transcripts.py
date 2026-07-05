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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import yaml

from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.repository import migrate, upsert

SYNTHETIC_MODEL = "<synthetic>"
PRICING_PATH = Path(__file__).parent.parent / "ledger" / "pricing.yaml"


@dataclass(frozen=True)
class Price:
    """Per-thousand-token rates for one model."""

    input_rate: float
    output_rate: float


@dataclass
class Bucket:
    """Aggregated usage for one model within a transcript."""

    session_id: str
    in_tokens: int = 0
    out_tokens: int = 0
    calls: int = 0
    last_ts: str = ""


def _pricing() -> dict[str, Price]:
    """Load and validate the versioned local pricing table."""

    raw: object = yaml.safe_load(PRICING_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("pricing table must be a mapping")
    root = cast("dict[object, object]", raw)
    sku_values = root.get("skus")
    if not isinstance(sku_values, dict):
        raise ValueError("pricing table must define a 'skus' mapping")

    prices: dict[str, Price] = {}
    for model, value in cast("dict[object, object]", sku_values).items():
        if not isinstance(model, str) or not isinstance(value, dict):
            raise ValueError("each pricing entry must map a model name to rates")
        rates = cast("dict[object, object]", value)
        input_rate = rates.get("input")
        output_rate = rates.get("output")
        if not isinstance(input_rate, (int, float)) or not isinstance(
            output_rate, (int, float)
        ):
            raise ValueError(f"pricing entry for {model!r} has invalid rates")
        prices[model] = Price(float(input_rate), float(output_rate))
    return prices


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


def parse_transcript(path: Path) -> list[CallRecord]:
    """Aggregate one transcript into per-model records with project context."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    buckets: dict[str, Bucket] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            decoded: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(decoded, dict):
            continue
        record = cast("dict[object, object]", decoded)
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
        bucket = buckets.setdefault(model, Bucket(session_id=session_id))
        bucket.in_tokens += _token_count(usage.get("input_tokens"))
        bucket.in_tokens += _token_count(usage.get("cache_creation_input_tokens"))
        bucket.out_tokens += _token_count(usage.get("output_tokens"))
        bucket.calls += 1
        timestamp = str(record.get("timestamp") or "")
        if timestamp > bucket.last_ts:
            bucket.last_ts = timestamp

    prices = _pricing()
    records: list[CallRecord] = []
    for model, bucket in buckets.items():
        price = prices.get(model)
        if price is None:
            raise ValueError(f"no pricing configured for transcript model {model!r}")
        capability_class, vendor = classify(model)
        records.append(
            CallRecord(
                ts=_timestamp(bucket.last_ts, path),
                session_id=bucket.session_id,
                project=path.parent.name,
                model_sku=model,
                capability_class=capability_class,
                vendor=vendor,
                in_tokens=bucket.in_tokens,
                out_tokens=bucket.out_tokens,
                cost_usd=(
                    bucket.in_tokens / 1000 * price.input_rate
                    + bucket.out_tokens / 1000 * price.output_rate
                ),
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
