"""Build and smoke-test the exact disposable recovery demonstration."""

from __future__ import annotations

import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING

import uvicorn

from agent_ledger.api.app import TOKEN_HEADER, create_app
from agent_ledger.recovery.assembler import recover_session
from agent_ledger.recovery.prompt import render_recovery_prompt

if TYPE_CHECKING:
    from pathlib import Path

    from agent_ledger.recovery.models import RecoveryBrief


class DemoError(RuntimeError):
    """Raised when the disposable demo cannot be created or verified."""


@dataclass(frozen=True)
class DemoScenario:
    """Paths and output for one synthetic recovery scenario."""

    root: Path
    repo: Path
    transcript: Path
    brief: RecoveryBrief
    prompt: str


@dataclass(frozen=True)
class SmokeResult:
    """Observable results of the start/fetch/stop smoke cycle."""

    root_status: int
    api_status: int
    prompt_status: int
    server_stopped: bool


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
        Prepared repository, transcript, recovery brief, and safe prompt.

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

    fixture = (
        resources.files("agent_ledger.demo.fixture")
        .joinpath("session.jsonl")
        .read_text(encoding="utf-8")
    )
    transcript = root / "session.jsonl"
    transcript.write_text(fixture.replace("__DEMO_REPO__", str(repo)), encoding="utf-8")
    brief = recover_session(transcript, repo)
    return DemoScenario(
        root=root,
        repo=repo,
        transcript=transcript,
        brief=brief,
        prompt=render_recovery_prompt(brief),
    )


def _fetch(url: str, token: str) -> int:
    request = urllib.request.Request(url, headers={TOKEN_HEADER: token})
    with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310
        return int(response.status)


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
        brief=scenario.brief,
        prompt=scenario.prompt,
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
    try:
        while time.monotonic() < deadline:
            try:
                root_status = _fetch(f"{root_url}/?token={token}", token)
                break
            except OSError:
                time.sleep(0.05)
        if root_status != 200:
            raise DemoError("demo server did not become ready")
        api_status = _fetch(f"{root_url}/api/recovery", token)
        prompt_status = _fetch(f"{root_url}/api/prompt", token)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        shutil.rmtree(base_dir)
    if thread.is_alive():
        raise DemoError("demo server did not stop cleanly")
    return SmokeResult(
        root_status=root_status,
        api_status=api_status,
        prompt_status=prompt_status,
        server_stopped=True,
    )
