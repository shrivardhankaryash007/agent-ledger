from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from agent_ledger.demo.scenario import build_demo_scenario, run_demo_smoke


def test_demo_fixture_exposes_exact_before_after_recovery(tmp_path: Path) -> None:
    scenario = build_demo_scenario(tmp_path / "demo")

    brief_payload = json.loads(scenario.brief.model_dump_json())
    fixture_text = (scenario.repo / "src/check.py").read_text(encoding="utf-8")

    assert "after" in fixture_text
    assert any(
        "differs from head" in item["statement"].lower()
        for item in brief_payload["observations"]
    )
    assert any(
        "unknown" in item["detail"].lower() for item in brief_payload["readiness"]
    )
    assert "pytest" not in scenario.brief.model_dump_json()


def test_packaged_console_and_demo_assets_are_present() -> None:
    package = resources.files("agent_ledger")

    assert package.joinpath("api/static/index.html").is_file()
    assert package.joinpath("api/static/app.css").is_file()
    assert package.joinpath("api/static/app.js").is_file()
    assert package.joinpath("demo/fixture/session.jsonl").is_file()


def test_demo_smoke_starts_fetches_and_stops(tmp_path: Path) -> None:
    result = run_demo_smoke(base_dir=tmp_path / "smoke", port=0)

    assert result.root_status == 200
    assert result.api_status == 200
    assert result.prompt_status == 200
    assert result.server_stopped is True
