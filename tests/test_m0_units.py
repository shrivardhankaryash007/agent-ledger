"""Focused M0 unit and invariant tests."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from agent_ledger.ingest.claude_transcripts import classify, parse_transcript
from agent_ledger.ledger import pricing as pricing_module
from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.repository import all_records, migrate, upsert
from agent_ledger.report.spend import per_project

if TYPE_CHECKING:
    from pathlib import Path


def _priced_model(family: str) -> str:
    """Resolve a fixture model without duplicating versioned SKU literals."""

    return next(model for model in pricing_module.load_pricing() if family in model)


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("some-opus", ("frontier_deep", "anthropic")),
        ("some-fable", ("frontier_deep", "anthropic")),
        ("some-sonnet", ("coding_strong", "anthropic")),
        ("some-haiku", ("fast_small", "anthropic")),
        ("some-codex", ("coding_strong", "openai")),
        ("gpt-example", ("frontier_deep", "openai")),
        ("gemini-example", ("frontier_deep", "google")),
        ("grok-example", ("frontier_deep", "xai")),
        ("unknown", ("frontier_deep", "other")),
    ],
)
def test_classify(model: str, expected: tuple[str, str]) -> None:
    assert classify(model) == expected


def test_parse_transcript_skips_unusable_lines(tmp_path: Path) -> None:
    path = tmp_path / "project" / "session.jsonl"
    path.parent.mkdir()
    lines = [
        "",
        "{bad-json",
        "[]",
        "{}",
        json.dumps({"message": []}),
        json.dumps({"message": {"usage": {}}}),
        json.dumps({"message": {"model": "<synthetic>", "usage": {}}}),
        json.dumps({"message": {"model": _priced_model("haiku"), "usage": []}}),
        json.dumps(
            {
                "timestamp": "not-a-timestamp",
                "message": {
                    "model": _priced_model("haiku"),
                    "usage": {
                        "input_tokens": "bad",
                        "output_tokens": True,
                    },
                },
            }
        ),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    records = parse_transcript(path)

    assert len(records) == 1
    assert records[0].session_id == "session"
    assert records[0].project == "project"
    assert records[0].in_tokens == 0
    assert records[0].out_tokens == 0
    assert records[0].calls == 1
    assert records[0].ts.tzinfo is not None


def test_parse_transcript_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert parse_transcript(tmp_path / "missing.jsonl") == []


def test_parse_transcript_rejects_unpriced_model(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(
        json.dumps(
            {
                "message": {
                    "model": "unknown-model",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no pricing configured"):
        parse_transcript(path)


@pytest.mark.parametrize(
    "contents",
    [
        "[]",
        "skus: []",
        "skus:\n  1: []",
        "skus:\n  model: {input: invalid, output: 1}",
    ],
)
def test_parse_transcript_rejects_invalid_pricing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str
) -> None:
    pricing_path = tmp_path / "pricing.yaml"
    pricing_path.write_text(contents, encoding="utf-8")
    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(pricing_module, "PRICING_PATH", pricing_path)

    with pytest.raises(ValueError, match="pricing"):
        parse_transcript(transcript_path)


@settings(
    max_examples=20,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    first_in=st.integers(min_value=0, max_value=1_000_000),
    second_in=st.integers(min_value=0, max_value=1_000_000),
    first_out=st.integers(min_value=0, max_value=1_000_000),
    second_out=st.integers(min_value=0, max_value=1_000_000),
)
def test_cost_math_is_nonnegative_and_additive(
    tmp_path: Path,
    first_in: int,
    second_in: int,
    first_out: int,
    second_out: int,
) -> None:
    path = tmp_path / "project" / "session.jsonl"
    path.parent.mkdir(exist_ok=True)
    calls = [
        {
            "sessionId": "session",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "model": _priced_model("sonnet"),
                "usage": {"input_tokens": in_tokens, "output_tokens": out_tokens},
            },
        }
        for in_tokens, out_tokens in (
            (first_in, first_out),
            (second_in, second_out),
        )
    ]
    path.write_text("\n".join(json.dumps(call) for call in calls), encoding="utf-8")

    record = parse_transcript(path)[0]
    expected = (first_in + second_in) / 1000 * 0.003 + (
        first_out + second_out
    ) / 1000 * 0.015

    assert record.cost_usd >= 0
    assert record.cost_usd == pytest.approx(expected)
    assert record.in_tokens == first_in + second_in
    assert record.out_tokens == first_out + second_out


def test_repository_upsert_is_idempotent_and_rejects_wrong_schema(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "nested" / "ledger.db"
    original = CallRecord(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        session_id="session",
        project="first",
        model_sku="model",
        capability_class="coding_strong",
        vendor="other",
        in_tokens=1,
        out_tokens=2,
        cost_usd=0.1,
        calls=1,
    )
    updated = original.model_copy(
        update={"project": "updated", "in_tokens": 3, "cost_usd": 0.2}
    )

    upsert(db_path, original)
    upsert(db_path, updated)

    assert all_records(db_path) == [updated]

    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE schema_meta SET version = 999")
    with pytest.raises(RuntimeError, match="unsupported schema version"):
        migrate(db_path)


def test_per_project_returns_typed_empty_frame(tmp_path: Path) -> None:
    frame = per_project(tmp_path / "ledger.db")

    assert frame.is_empty()
    assert frame.columns == ["project", "in_tokens", "out_tokens", "cost_usd", "calls"]
