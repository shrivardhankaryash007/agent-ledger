"""Build and smoke-test the exact disposable recovery demonstration."""

from __future__ import annotations

import json
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING

import uvicorn

from agent_ledger.api.app import TOKEN_HEADER, create_app
from agent_ledger.recovery.adapters.claude_code import ClaudeCodeAdapter
from agent_ledger.recovery.adapters.codex import CodexAdapter
from agent_ledger.recovery.catalog import RecoveryCatalog
from agent_ledger.recovery.discovery import AdapterRoot, discover_sessions
from agent_ledger.recovery.models import (
    HandoffStatus,
    ReceiptApplicability,
    RecoveryPackage,
)
from agent_ledger.recovery.package import recovery_brief_digest
from agent_ledger.recovery.prompt import render_recovery_prompt
from agent_ledger.recovery.receipts import ReceiptStore, run_verification

if TYPE_CHECKING:
    from pathlib import Path

    from agent_ledger.recovery.models import RecoveryBrief


class DemoError(RuntimeError):
    """Raised when the disposable demo cannot be created or verified."""


@dataclass(frozen=True)
class DemoScenario:
    """Paths and output for synthetic recovery scenarios."""

    root: Path
    repo: Path
    transcript: Path
    codex_transcript: Path
    brief: RecoveryBrief
    prompt: str
    catalog: RecoveryCatalog
    store: ReceiptStore
    candidate_id: str
    codex_candidate_id: str


@dataclass(frozen=True)
class SmokeResult:
    """Observable results of the start/fetch/stop smoke cycle."""

    root_status: int
    api_status: int
    prompt_status: int
    server_stopped: bool
    inbox_status: int = 200
    receipt_status: int = 200
    package_status: int = 200
    package_verified: bool = True


def demo_verification_command() -> tuple[str, ...]:
    """Safe cross-platform verification command owned by the package."""
    return (sys.executable, "-c", "import sys; sys.exit(0)")


def _run_git(repo: Path, arguments: tuple[str, ...]) -> None:
    try:
        subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DemoError("synthetic demo repository could not be prepared") from exc


def build_demo_scenario(root: Path) -> DemoScenario:
    """Create the exact synthetic before/after interrupted-session scenario.

    Args:
        root: New empty directory dedicated to the disposable demo.

    Returns:
        Prepared repository, transcripts, catalog, recovery brief, and safe prompt.

    Raises:
        DemoError: If the target is non-empty or Git setup fails.
    """

    if root.exists() and any(root.iterdir()):
        raise DemoError("demo target must be empty")
    root.mkdir(parents=True, exist_ok=True)
    repo = root / "recovery-demo"
    repo.mkdir()
    _run_git(repo, ("init", "-q", "-b", "main"))
    _run_git(repo, ("config", "user.email", "demo@example.invalid"))
    _run_git(repo, ("config", "user.name", "Agent Ledger Demo"))
    source = repo / "src/check.py"
    source.parent.mkdir(parents=True)
    source.write_text("VERIFICATION_STATE = 'before'\n", encoding="utf-8")
    _run_git(repo, ("add", "--", "src/check.py"))
    _run_git(repo, ("commit", "-qm", "demo: seed before state"))
    source.write_text("VERIFICATION_STATE = 'after'\n", encoding="utf-8")

    claude_fixture = (
        resources.files("agent_ledger.demo.fixture")
        .joinpath("session.jsonl")
        .read_text(encoding="utf-8")
    )
    claude_transcript = root / "session.jsonl"
    claude_transcript.write_text(
        claude_fixture.replace("__DEMO_REPO__", str(repo)), encoding="utf-8"
    )

    codex_fixture = (
        resources.files("agent_ledger.demo.fixture")
        .joinpath("codex-session.jsonl")
        .read_text(encoding="utf-8")
    )
    codex_transcript = root / "codex-session.jsonl"
    codex_transcript.write_text(
        codex_fixture.replace("__DEMO_REPO__", str(repo)), encoding="utf-8"
    )

    claude_adapter = ClaudeCodeAdapter()
    codex_adapter = CodexAdapter()
    discovered = discover_sessions(
        repo=repo,
        roots=(
            AdapterRoot(adapter=claude_adapter, root=root),
            AdapterRoot(adapter=codex_adapter, root=root),
        ),
    )
    catalog = RecoveryCatalog(
        repo=repo,
        discovery=discovered,
        adapters=(claude_adapter, codex_adapter),
    )
    claude_candidate_id = ""
    codex_candidate_id = ""
    for session in discovered.sessions:
        if session.candidate.provider == "claude-code":
            claude_candidate_id = session.candidate.candidate_id
        elif session.candidate.provider == "codex":
            codex_candidate_id = session.candidate.candidate_id

    if not claude_candidate_id or not codex_candidate_id:
        raise DemoError("could not discover synthetic demo candidates")

    brief = catalog.recover(claude_candidate_id)
    prompt = render_recovery_prompt(brief)
    store = ReceiptStore(root / "receipts")

    return DemoScenario(
        root=root,
        repo=repo,
        transcript=claude_transcript,
        codex_transcript=codex_transcript,
        brief=brief,
        prompt=prompt,
        catalog=catalog,
        store=store,
        candidate_id=claude_candidate_id,
        codex_candidate_id=codex_candidate_id,
    )


def _fetch(url: str, token: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={TOKEN_HEADER: token})
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        return int(response.status), response.read()


def run_demo_smoke(*, base_dir: Path, port: int = 0) -> SmokeResult:
    """Start, fetch, stop, and clean a real localhost demo server.

    Args:
        base_dir: Dedicated disposable directory removed after the smoke cycle.
        port: Requested localhost port; zero asks the OS for a free port.

    Returns:
        HTTP statuses and proof that the server thread stopped.

    Raises:
        DemoError: If the server does not start or stop in time.
    """

    scenario = build_demo_scenario(base_dir)
    token = secrets.token_urlsafe(24)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(128)
    actual_port = int(listener.getsockname()[1])
    app = create_app(
        catalog=scenario.catalog,
        receipt_store=scenario.store,
        capability_token=token,
        port=actual_port,
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=actual_port, log_level="error")
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="agent-ledger-demo-smoke",
        daemon=True,
    )
    thread.start()
    root_url = f"http://127.0.0.1:{actual_port}"
    deadline = time.monotonic() + 5
    root_status = 0
    inbox_status = 0
    api_status = 0
    prompt_status = 0
    receipt_status = 0
    package_status = 0
    package_verified = False
    try:
        while time.monotonic() < deadline:
            try:
                root_status, _ = _fetch(f"{root_url}/?token={token}", token)
                break
            except OSError:
                time.sleep(0.05)
        if root_status != 200:
            raise DemoError("demo server did not become ready")

        inbox_status, inbox_bytes = _fetch(f"{root_url}/api/sessions", token)
        inbox_data = json.loads(inbox_bytes)
        if len(inbox_data.get("sessions", [])) < 2:
            raise DemoError("inbox catalog did not return expected demo sessions")

        api_status, _ = _fetch(
            f"{root_url}/api/sessions/{scenario.candidate_id}/recovery", token
        )
        prompt_status, _ = _fetch(
            f"{root_url}/api/sessions/{scenario.candidate_id}/prompt", token
        )

        missing_status, missing_bytes = _fetch(
            f"{root_url}/api/sessions/{scenario.candidate_id}/receipt", token
        )
        if missing_status != 200:
            raise DemoError("missing receipt endpoint did not return 200")
        missing_data = json.loads(missing_bytes)
        if missing_data.get("applicability") != "missing":
            raise DemoError("initial receipt state must be missing")

        receipt = run_verification(
            repo=scenario.catalog.trusted_repo,
            candidate_id=scenario.candidate_id,
            brief_digest=recovery_brief_digest(scenario.brief),
            owner_label="demo-smoke-verification",
            argv=demo_verification_command(),
            timeout_seconds=5,
        )
        scenario.store.save(receipt)

        receipt_status, current_bytes = _fetch(
            f"{root_url}/api/sessions/{scenario.candidate_id}/receipt", token
        )
        current_data = json.loads(current_bytes)
        if current_data.get("applicability") != "current":
            raise DemoError("receipt state after verification must be current")

        package_status, package_bytes = _fetch(
            f"{root_url}/api/sessions/{scenario.candidate_id}/package", token
        )
        package = RecoveryPackage.model_validate_json(package_bytes)
        if package.handoff_status != HandoffStatus.current_exit_zero:
            raise DemoError("recovery package handoff status must be current_exit_zero")
        if package.receipt_applicability != ReceiptApplicability.current:
            raise DemoError("recovery package applicability must be current")
        package_verified = True
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        shutil.rmtree(base_dir, ignore_errors=True)
    if thread.is_alive():
        raise DemoError("demo server did not stop cleanly")
    return SmokeResult(
        root_status=root_status,
        api_status=api_status,
        prompt_status=prompt_status,
        server_stopped=True,
        inbox_status=inbox_status,
        receipt_status=receipt_status,
        package_status=package_status,
        package_verified=package_verified,
    )
