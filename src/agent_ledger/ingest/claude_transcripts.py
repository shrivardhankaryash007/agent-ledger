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

from pathlib import Path

from agent_ledger.ledger.models import CallRecord


def classify(model: str) -> tuple[str, str]:
    """Map a transcript model id to (capability_class, vendor).

    M0 TODO: substring classification, no full SKU literals (vendor
    neutrality), mirroring the logic already proven in ide_meter.classify.
    """

    raise NotImplementedError("M0: implement classify()")


def parse_transcript(path: Path) -> list[CallRecord]:
    """Aggregate one transcript file into per-model CallRecords, with
    `project` set from `path.parent.name`.

    M0 TODO: parse JSONL lines, sum usage per model, price via pricing table.
    """

    raise NotImplementedError("M0: implement parse_transcript()")


def ingest(source_dir: Path, db_path: Path) -> int:
    """Scan source_dir for transcripts and upsert CallRecords into db_path.

    Returns the number of records written.

    M0 TODO: walk source_dir.rglob("*.jsonl"), call parse_transcript per
    file, repository.upsert each record. Idempotent.
    """

    raise NotImplementedError("M0: implement ingest()")
