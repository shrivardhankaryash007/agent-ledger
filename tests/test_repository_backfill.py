"""Repository helpers used only by the one-off 2026-08 backfill."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.repository import (
    all_records,
    delete_by_session_ids,
    update_labels,
    upsert,
)


def _record(session_id: str) -> CallRecord:
    return CallRecord(
        ts=datetime(2026, 7, 1, tzinfo=UTC),
        session_id=session_id,
        project="dev",
        model_sku="claude-sonnet-4-6",
        capability_class="coding_strong",
        vendor="anthropic",
        in_tokens=100,
        out_tokens=20,
        cost_usd=0.001,
        calls=1,
    )


def test_delete_by_session_ids_removes_only_matching_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    upsert(db_path, _record("sess-a:dev"))
    upsert(db_path, _record("sess-b:careledger"))

    deleted = delete_by_session_ids(db_path, ["sess-a:dev"])

    assert deleted == 1
    remaining = {r.session_id for r in all_records(db_path)}
    assert remaining == {"sess-b:careledger"}


def test_delete_by_session_ids_empty_list_is_a_no_op(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    upsert(db_path, _record("sess-a:dev"))

    deleted = delete_by_session_ids(db_path, [])

    assert deleted == 0
    assert len(all_records(db_path)) == 1


def test_update_labels_leaves_tokens_and_cost_untouched(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    original = _record("sess-a:dev")
    upsert(db_path, original)

    update_labels(
        db_path,
        session_id="sess-a:dev",
        model_sku="claude-sonnet-4-6",
        repo_name="dev",
        worktree_name=None,
        branch="main",
        label_source="git",
    )

    (record,) = all_records(db_path)
    assert record.repo_name == "dev"
    assert record.branch == "main"
    assert record.label_source == "git"
    # The historical record itself must be untouched by a label backfill.
    assert record.in_tokens == original.in_tokens
    assert record.cost_usd == original.cost_usd
    assert record.project == original.project
