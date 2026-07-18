from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from agent_ledger.api.app import create_app
from agent_ledger.recovery.adapters.codex import CodexAdapter
from agent_ledger.recovery.catalog import RecoveryCatalog
from agent_ledger.recovery.discovery import AdapterRoot, discover_sessions
from agent_ledger.recovery.git_state import UnsafeRecoveryPathError
from agent_ledger.recovery.models import (
    Certainty,
    ContinuationAction,
    EvidenceKind,
    EvidenceRef,
    Observation,
    ReadinessCheck,
    ReadinessStatus,
    RecoveryBrief,
    SourceAdapter,
    Uncertainty,
)


def _brief() -> RecoveryBrief:
    evidence = EvidenceRef(
        id="ev-test",
        kind=EvidenceKind.git,
        label="Current Git snapshot",
        locator="git:head",
        digest="a" * 64,
    )
    return RecoveryBrief(
        generated_at=datetime(2026, 7, 17, 9, 30, tzinfo=UTC),
        session_id="demo-session",
        project="recovery-demo",
        repo_name="recovery-demo",
        branch="main",
        head="b" * 40,
        ending="unknown",
        intent="Finish the verification flow.",
        source_adapter=SourceAdapter(name="claude-code-jsonl", version=1),
        observations=(
            Observation(
                id="observation",
                statement="Current file differs from HEAD.",
                certainty=Certainty.observed,
                evidence_ids=(evidence.id,),
            ),
        ),
        uncertainties=(
            Uncertainty(
                id="uncertainty",
                statement="Verification outcome is unknown.",
                evidence_ids=(evidence.id,),
            ),
        ),
        readiness=(
            ReadinessCheck(
                id="verification",
                label="Recorded verification",
                status=ReadinessStatus.unknown,
                detail="No matching result.",
                evidence_ids=(evidence.id,),
            ),
        ),
        actions=(
            ContinuationAction(
                template_id="recovery.inspect-current-diff",
                position=1,
                instruction="Inspect the current diff before editing.",
            ),
        ),
        evidence=(evidence,),
    )


def _client() -> TestClient:
    return TestClient(
        create_app(
            brief=_brief(),
            prompt="safe continuation prompt",
            capability_token="test-token",
            allowed_hosts=frozenset({"testserver"}),
            allowed_origins=frozenset({"http://testserver"}),
        )
    )


def _catalog_client(tmp_path: Path) -> tuple[TestClient, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "demo@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Recovery Test"],
        check=True,
    )
    (repo / "safe.py").write_text("SAFE = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "--", "safe.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "seed"],
        check=True,
    )
    transcript = tmp_path / "codex-sessions" / "rollout.jsonl"
    transcript.parent.mkdir()
    records = [
        {
            "timestamp": "2026-07-18T00:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "catalog-session",
                "cwd": str(repo),
                "timestamp": "2026-07-18T00:00:00Z",
            },
        },
        {
            "timestamp": "2026-07-18T00:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": "Continue the safe recovery flow.",
            },
        },
        {
            "timestamp": "2026-07-18T00:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": "call-missing",
                "name": "exec",
                "status": "completed",
                "input": "private-command --secret fixture-value",
            },
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    adapter = CodexAdapter()
    discovery = discover_sessions(
        repo=repo,
        roots=(AdapterRoot(adapter=adapter, root=transcript.parent),),
    )
    catalog = RecoveryCatalog(
        repo=repo,
        discovery=discovery,
        adapters=(adapter,),
    )
    candidate_id = discovery.sessions[0].candidate.candidate_id
    client = TestClient(
        create_app(
            catalog=catalog,
            capability_token="test-token",
            allowed_hosts=frozenset({"testserver"}),
            allowed_origins=frozenset({"http://testserver"}),
        )
    )
    return client, transcript, candidate_id


def test_console_bootstrap_requires_capability_token_and_sets_security_headers() -> (
    None
):
    client = _client()

    assert client.get("/").status_code == 401
    response = client.get("/?token=test-token")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "safe continuation prompt" not in response.text
    assert "https://" not in response.text


def test_console_api_rejects_bad_token_host_and_origin() -> None:
    client = _client()

    assert client.get("/api/recovery").status_code == 401
    assert (
        client.get(
            "/api/recovery",
            headers={"X-Agent-Ledger-Token": "test-token", "Host": "evil.test"},
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/api/recovery",
            headers={
                "X-Agent-Ledger-Token": "test-token",
                "Origin": "https://evil.test",
            },
        ).status_code
        == 403
    )


def test_console_api_returns_brief_and_prompt_without_cors() -> None:
    client = _client()
    headers = {
        "X-Agent-Ledger-Token": "test-token",
        "Origin": "http://testserver",
    }

    brief_response = client.get("/api/recovery", headers=headers)
    prompt_response = client.get("/api/prompt", headers=headers)

    assert brief_response.status_code == 200
    assert brief_response.json()["session_id"] == "demo-session"
    assert prompt_response.json() == {"prompt": "safe continuation prompt"}
    assert "access-control-allow-origin" not in brief_response.headers


def test_catalog_api_lists_redacted_candidates_and_lazily_assembles_brief(
    tmp_path: Path,
) -> None:
    client, _, candidate_id = _catalog_client(tmp_path)
    headers = {"X-Agent-Ledger-Token": "test-token"}

    sessions_response = client.get("/api/sessions", headers=headers)
    brief_response = client.get(
        f"/api/sessions/{candidate_id}/recovery",
        headers=headers,
    )
    prompt_response = client.get(
        f"/api/sessions/{candidate_id}/prompt",
        headers=headers,
    )

    assert sessions_response.status_code == 200
    sessions_payload = sessions_response.json()
    assert sessions_payload["repo_name"] == "repo"
    assert sessions_payload["excluded_count"] == 0
    assert sessions_payload["sessions"][0]["candidate_id"] == candidate_id
    serialized_sessions = json.dumps(sessions_payload)
    assert str(tmp_path) not in serialized_sessions
    assert "private-command" not in serialized_sessions
    assert brief_response.status_code == 200
    assert brief_response.json()["session_id"] == "catalog-session"
    assert prompt_response.status_code == 200
    assert "# Verified recovery brief" in prompt_response.json()["prompt"]
    assert "private-command" not in (brief_response.text + prompt_response.text)
    assert client.get("/api/recovery", headers=headers).status_code == 404


def test_catalog_rejects_unknown_candidate_and_source_drift(tmp_path: Path) -> None:
    client, transcript, candidate_id = _catalog_client(tmp_path)
    headers = {"X-Agent-Ledger-Token": "test-token"}

    assert (
        client.get(
            "/api/sessions/not-a-candidate/recovery", headers=headers
        ).status_code
        == 404
    )
    transcript.write_text(
        transcript.read_text(encoding="utf-8") + "{}\n",
        encoding="utf-8",
    )
    drifted = client.get(
        f"/api/sessions/{candidate_id}/recovery",
        headers=headers,
    )

    assert drifted.status_code == 409
    assert drifted.json() == {"detail": "session source changed; restart discovery"}


def test_catalog_redacts_unsafe_reconciliation_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def reject_unsafe_path(
        self: RecoveryCatalog,
        candidate_id: str,
    ) -> None:
        raise UnsafeRecoveryPathError("private path must not reach the response")

    monkeypatch.setattr(RecoveryCatalog, "recover", reject_unsafe_path)
    client, _, candidate_id = _catalog_client(tmp_path)

    response = client.get(
        f"/api/sessions/{candidate_id}/recovery",
        headers={"X-Agent-Ledger-Token": "test-token"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "session evidence could not be reconciled safely"
    }
    assert "private path" not in response.text


def test_compatibility_mode_keeps_legacy_aliases_without_catalog() -> None:
    client = _client()
    headers = {"X-Agent-Ledger-Token": "test-token"}

    assert client.get("/api/recovery", headers=headers).status_code == 200
    assert client.get("/api/prompt", headers=headers).status_code == 200
    assert client.get("/api/sessions", headers=headers).status_code == 404


def test_static_assets_are_capability_protected() -> None:
    client = _client()

    assert client.get("/static/app.js").status_code == 401
    response = client.get(
        "/static/app.js", headers={"X-Agent-Ledger-Token": "test-token"}
    )

    assert response.status_code == 200
    assert "innerHTML" not in response.text

    html = client.get("/", headers={"X-Agent-Ledger-Token": "test-token"}).text
    assert "Recovery Inbox" in html
    assert 'id="session-list"' in html
    assert 'id="back-to-inbox"' in html
    assert "JavaScript is required" in html
    assert 'aria-live="polite"' in html
    assert 'fetch("/api/sessions"' in response.text
