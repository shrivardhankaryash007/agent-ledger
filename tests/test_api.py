from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from agent_ledger.api.app import create_app
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


def test_static_assets_are_capability_protected() -> None:
    client = _client()

    assert client.get("/static/app.js").status_code == 401
    response = client.get(
        "/static/app.js", headers={"X-Agent-Ledger-Token": "test-token"}
    )

    assert response.status_code == 200
    assert "innerHTML" not in response.text
