"""M4 acceptance: one API response is counted once, however many lines it spans.

Written to fail before the fix exists (AGENTS.md rule 5).

The defect these tests pin down: Claude Code writes one API response as
several JSONL lines (one per content block — thinking, text, each tool_use),
all sharing `message.id` and repeating the same `usage` object. The first line
carries a partial `output_tokens` (the streaming snapshot at block start); the
last line carries the final figure. `parse_transcript` added the usage of
*every* line, so on the real corpus (192 transcripts, 6,164 responses spread
over 12,988 usage lines) cost was overstated 2.22x and output tokens 2.52x.
See docs/decisions/0007-dedupe-transcript-usage-by-message-id.md.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from agent_ledger.ingest.claude_transcripts import ingest, parse_transcript
from agent_ledger.ledger.models import MODEL_VERSION
from agent_ledger.ledger.pricing import cost_usd, load_pricing
from agent_ledger.ledger.repository import all_records

PRICED_MODEL = "claude-sonnet-5"

Usage = dict[str, int]


def _usage(out: int, *, inp: int = 10, read: int = 1_000, write: int = 200) -> Usage:
    return {
        "input_tokens": inp,
        "cache_creation_input_tokens": write,
        "cache_read_input_tokens": read,
        "output_tokens": out,
    }


def _line(
    message_id: str | None, usage: Usage, minute: int, *, block: str = "text"
) -> str:
    message: dict[str, object] = {
        "model": PRICED_MODEL,
        "usage": usage,
        "content": [{"type": block}],
    }
    if message_id is not None:
        message["id"] = message_id
    return json.dumps(
        {
            "sessionId": "sess-m4",
            "cwd": "/nonexistent/m4",
            "timestamp": f"2026-10-02T10:{minute:02d}:00Z",
            "message": message,
        }
    )


def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_three_lines_of_one_message_count_once(tmp_path: Path) -> None:
    """The acceptance case: 3 content-block lines, one message.id, count once."""

    transcript = _write(
        tmp_path / "sess-m4.jsonl",
        [
            _line("msg_A", _usage(out=8), 0, block="thinking"),
            _line("msg_A", _usage(out=8), 1, block="text"),
            _line("msg_A", _usage(out=412), 2, block="tool_use"),
        ],
    )

    (record,) = parse_transcript(transcript)

    assert record.calls == 1, "`calls` is API responses, not transcript lines"
    assert record.cache_read_tokens == 1_000
    assert record.cache_write_tokens == 200
    assert record.in_tokens == 10 + 200
    assert record.out_tokens == 412, "the LAST line carries the final output_tokens"


def test_last_line_wins_even_when_it_is_the_smaller_figure(tmp_path: Path) -> None:
    """'Last wins' is positional, not 'max' — the rule must not be a heuristic."""

    transcript = _write(
        tmp_path / "sess-m4.jsonl",
        [_line("msg_A", _usage(out=500), 0), _line("msg_A", _usage(out=300), 1)],
    )

    (record,) = parse_transcript(transcript)

    assert record.out_tokens == 300


def test_distinct_messages_still_sum_and_interleaving_is_handled(
    tmp_path: Path,
) -> None:
    """Dedup is by id, not by adjacency: B sits between two lines of A."""

    transcript = _write(
        tmp_path / "sess-m4.jsonl",
        [
            _line("msg_A", _usage(out=5), 0),
            _line("msg_B", _usage(out=70), 1),
            _line("msg_A", _usage(out=90), 2),
        ],
    )

    (record,) = parse_transcript(transcript)

    assert record.calls == 2
    assert record.out_tokens == 90 + 70
    assert record.cache_read_tokens == 2_000


def test_lines_without_message_id_are_each_counted(tmp_path: Path) -> None:
    """No id means no safe way to merge — keep v3 behaviour for those lines."""

    transcript = _write(
        tmp_path / "sess-m4.jsonl",
        [_line(None, _usage(out=10), 0), _line(None, _usage(out=10), 1)],
    )

    (record,) = parse_transcript(transcript)

    assert record.calls == 2
    assert record.out_tokens == 20


def test_cost_is_priced_from_the_deduplicated_usage(tmp_path: Path) -> None:
    """cost_usd must equal the cost of ONE response, not three."""

    transcript = _write(
        tmp_path / "sess-m4.jsonl",
        [_line("msg_A", _usage(out=412), minute) for minute in range(3)],
    )

    (record,) = parse_transcript(transcript)

    expected = cost_usd(
        PRICED_MODEL,
        210,
        412,
        load_pricing(),
        cache_read_tokens=1_000,
        cache_write_tokens=200,
    )
    assert record.cost_usd == expected


def test_timestamp_is_still_the_latest_line_in_the_transcript(
    tmp_path: Path,
) -> None:
    """Row `ts` was max(line ts) before the fix; de-dup must not move it."""

    transcript = _write(
        tmp_path / "sess-m4.jsonl",
        [_line("msg_A", _usage(out=1), 0), _line("msg_A", _usage(out=9), 7)],
    )

    (record,) = parse_transcript(transcript)

    assert record.ts.minute == 7


def test_reingest_is_idempotent_and_stamps_model_version(tmp_path: Path) -> None:
    """Two ingests over the same corpus: same rows, same totals, new version."""

    source = tmp_path / "projects" / "p"
    source.mkdir(parents=True)
    _write(
        source / "sess-m4.jsonl",
        [_line("msg_A", _usage(out=412), minute) for minute in range(3)],
    )
    db_path = tmp_path / "ledger.db"

    ingest(tmp_path / "projects", db_path)
    first = [r.model_dump() for r in all_records(db_path)]
    ingest(tmp_path / "projects", db_path)
    second = [r.model_dump() for r in all_records(db_path)]

    assert first == second
    assert len(first) == 1
    assert first[0]["calls"] == 1
    assert first[0]["model_version"] == MODEL_VERSION
    assert MODEL_VERSION >= 4, "de-dup changes stored numbers: ADR 0007 bumps to 4"


@settings(max_examples=60, deadline=None)
@given(
    outs=st.lists(st.integers(min_value=0, max_value=5_000), min_size=1, max_size=8),
    repeats=st.lists(st.integers(min_value=1, max_value=5), min_size=1, max_size=8),
)
def test_property_repeating_lines_never_changes_the_totals(
    outs: list[int], repeats: list[int]
) -> None:
    """Invariant: result == sum over distinct ids of their LAST line's usage."""

    count = min(len(outs), len(repeats))
    lines: list[str] = []
    minute = 0
    for index in range(count):
        for _ in range(repeats[index]):
            lines.append(_line(f"msg_{index}", _usage(out=outs[index]), minute % 60))
            minute += 1

    with tempfile.TemporaryDirectory() as raw_dir:
        transcript = _write(Path(raw_dir) / "sess-m4.jsonl", lines)
        (record,) = parse_transcript(transcript)

    assert record.calls == count
    assert record.out_tokens == sum(outs[:count])
    assert record.cache_read_tokens == 1_000 * count
