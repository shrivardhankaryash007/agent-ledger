"""Packet AL-D acceptance: subagent transcripts must not overwrite their parent (red first).

Facts (ADR 0007 follow-up #1, STATUS.md): Claude Code writes a subagent's
transcript to ``<project>/<session>/subagents/agent-<id>.jsonl`` and every line
there carries the PARENT's ``sessionId``. ``parse_transcript`` keys a bucket by
``<sessionId>:<tag>`` and the repository upserts on ``(session_id, model_sku)``, so
a subagent's usage replaces the parent's row instead of adding to it. About
$121 (26%) of corpus spend never reaches the database.

These tests pin the OBSERVABLE contract only. How the subagent rows are keyed is
the packet's design decision and is not prescribed here.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_ledger.ingest.claude_transcripts import ingest
from agent_ledger.ledger.pricing import cost_usd, load_pricing
from agent_ledger.ledger.repository import all_records

MODEL = "claude-sonnet-5-5"
PARENT_ID = "parentsession"


def _line(message_id: str, in_tokens: int, out_tokens: int) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "sessionId": PARENT_ID,
            "timestamp": "2026-10-01T10:00:00Z",
            "message": {
                "id": message_id,
                "model": MODEL,
                "usage": {"input_tokens": in_tokens, "output_tokens": out_tokens},
            },
        }
    )


def _source(tmp_path: Path, *, with_subagent: bool = True) -> Path:
    project = tmp_path / "projects" / "-proj"
    project.mkdir(parents=True)
    (project / f"{PARENT_ID}.jsonl").write_text(_line("msg_parent", 100, 10) + "\n", "utf-8")
    if with_subagent:
        sub = project / PARENT_ID / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-abc123.jsonl").write_text(_line("msg_sub", 200, 20) + "\n", "utf-8")
    return tmp_path / "projects"


def test_parent_and_subagent_usage_both_reach_the_ledger(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    ingest(_source(tmp_path), db)

    records = all_records(db)
    prices = load_pricing()
    assert sum(r.in_tokens for r in records) == 300
    assert sum(r.out_tokens for r in records) == 30
    assert sum(r.calls for r in records) == 2
    expected = cost_usd(MODEL, 100, 10, prices) + cost_usd(MODEL, 200, 20, prices)
    assert abs(sum(r.cost_usd for r in records) - expected) < 1e-9


def test_reingesting_changes_nothing(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    source = _source(tmp_path)
    ingest(source, db)
    first = sorted((r.session_id, r.model_sku, r.in_tokens, r.calls) for r in all_records(db))
    ingest(source, db)
    second = sorted((r.session_id, r.model_sku, r.in_tokens, r.calls) for r in all_records(db))
    assert first == second


def test_an_ordinary_session_keeps_its_existing_key(tmp_path: Path) -> None:
    """Rows already in the ledger must not be re-keyed (collected data is the asset)."""

    db = tmp_path / "ledger.db"
    ingest(_source(tmp_path, with_subagent=False), db)
    ids = [r.session_id for r in all_records(db)]
    assert ids == [f"{PARENT_ID}:unknown"]


def test_subagent_rows_are_distinguishable_from_the_parent(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    ingest(_source(tmp_path), db)
    ids = {r.session_id for r in all_records(db)}
    assert len(ids) == 2
    assert f"{PARENT_ID}:unknown" in ids


def test_the_decision_is_recorded_in_an_adr() -> None:
    root = Path(__file__).resolve().parents[1]
    adrs = sorted((root / "docs" / "decisions").glob("0008-*.md"))
    assert len(adrs) == 1, "write exactly one docs/decisions/0008-*.md"
    text = adrs[0].read_text(encoding="utf-8").lower()
    assert "subagent" in text and "alternatives" in text and "consequences" in text
