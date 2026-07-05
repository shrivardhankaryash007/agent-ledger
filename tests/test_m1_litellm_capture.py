"""M1 acceptance test (docs/architecture.md).

Drives AgentLedgerLoggerCallback.log_success_event with a payload shaped
exactly like a real litellm success event — captured by running one real
completion through a local Ollama model and inspecting kwargs/response_obj
directly (see docs/architecture.md § M1 for the probe transcript). This
keeps the automated suite hermetic (no live Ollama dependency in CI) while
pinning the exact real contract, not a guessed one.

FAILS now because record_from_event()/classify() raise NotImplementedError.
Passes only once one CallRecord lands in the DB with project sourced from
metadata.caller_tag, tokens from response_obj.usage, and vendor/capability
class derived from custom_llm_provider — the M1 acceptance criterion
("live call captured with caller-tag attribution") encoded as a check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_ledger.ingest.litellm_proxy import AgentLedgerLoggerCallback
from agent_ledger.ledger.repository import all_records


@dataclass
class FakeUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def _real_shaped_kwargs(*, caller_tag: str | None) -> dict[str, object]:
    """Mirrors the exact kwargs litellm passed to log_success_event for a
    real `litellm.completion(model="ollama/gemma4:latest", ...)` call."""

    metadata: dict[str, object] = {}
    if caller_tag is not None:
        metadata["caller_tag"] = caller_tag
    return {
        "model": "gemma4:latest",
        "custom_llm_provider": "ollama",
        "litellm_call_id": "fe35a116-d35c-4cd8-bdd9-74f4af90b039",
        "litellm_params": {"metadata": metadata},
        "response_cost": 0.0,
    }


def test_captures_live_call_with_caller_tag(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    callback = AgentLedgerLoggerCallback(db_path)

    kwargs = _real_shaped_kwargs(caller_tag="agent-ledger-smoke-test")
    response_obj = SimpleNamespace(
        model="ollama/gemma4:latest",
        usage=FakeUsage(prompt_tokens=23, completion_tokens=87, total_tokens=110),
    )
    end_time = datetime(2026, 7, 5, 9, 30, tzinfo=UTC)

    callback.log_success_event(kwargs, response_obj, end_time, end_time)

    records = all_records(db_path)
    assert len(records) == 1
    record = records[0]
    assert record.project == "agent-ledger-smoke-test"
    assert record.model_sku == "gemma4:latest"
    assert record.vendor == "ollama"
    assert record.capability_class == "local_fast"
    assert record.in_tokens == 23
    assert record.out_tokens == 87
    assert record.cost_usd == pytest.approx(0.0)
    assert record.calls == 1


def test_missing_caller_tag_falls_back_to_unknown(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    callback = AgentLedgerLoggerCallback(db_path)

    kwargs = _real_shaped_kwargs(caller_tag=None)
    response_obj = SimpleNamespace(
        model="ollama/gemma4:latest",
        usage=FakeUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
    )
    end_time = datetime(2026, 7, 5, 9, 31, tzinfo=UTC)

    callback.log_success_event(kwargs, response_obj, end_time, end_time)

    records = all_records(db_path)
    assert records[0].project == "unknown"
