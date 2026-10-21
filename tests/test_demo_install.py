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
    assert package.joinpath("demo/fixture/codex-session.jsonl").is_file()


def test_demo_smoke_starts_fetches_and_stops(tmp_path: Path) -> None:
    result = run_demo_smoke(base_dir=tmp_path / "smoke", port=0)

    assert result.root_status == 200
    assert result.inbox_status == 200
    assert result.api_status == 200
    assert result.prompt_status == 200
    assert result.receipt_status == 200
    assert result.package_status == 200
    assert result.package_verified is True
    assert result.server_stopped is True


def test_codex_demo_fixture_exposes_interrupted_signal(tmp_path: Path) -> None:
    scenario = build_demo_scenario(tmp_path / "demo-codex")
    codex_brief = scenario.catalog.recover(scenario.codex_candidate_id)

    candidates = {s.candidate_id: s for s in scenario.catalog.public.sessions}
    codex_candidate = candidates[scenario.codex_candidate_id]
    assert codex_candidate.ending.value == "interrupted"
    assert codex_candidate.unmatched_call_count == 1
    assert codex_brief.source_adapter.name == "codex-jsonl"
    assert any(
        "no matching tool result" in uncert.statement.lower()
        for uncert in codex_brief.uncertainties
    )


def test_built_wheel_contains_all_demo_and_console_assets(tmp_path: Path) -> None:
    import subprocess
    import sys
    import zipfile

    dist_dir = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    wheels = list(dist_dir.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        assert any(
            name.endswith("agent_ledger/api/static/index.html") for name in names
        )
        assert any(name.endswith("agent_ledger/api/static/app.js") for name in names)
        assert any(name.endswith("agent_ledger/api/static/app.css") for name in names)
        assert any(
            name.endswith("agent_ledger/demo/fixture/session.jsonl") for name in names
        )
        assert any(
            name.endswith("agent_ledger/demo/fixture/codex-session.jsonl")
            for name in names
        )

    disposable_dir = tmp_path / "disposable_run"
    disposable_dir.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_ledger.cli",
            "demo",
            "--no-open",
            "--smoke",
            "--port",
            "0",
        ],
        cwd=str(disposable_dir),
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "Demo smoke passed" in result.stdout
