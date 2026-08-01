"""Typer CLI: `agent-ledger ingest` / `agent-ledger report` / `agent-ledger replay`."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import webbrowser
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import typer
import uvicorn

from agent_ledger.api.app import create_app
from agent_ledger.demo.scenario import DemoError, build_demo_scenario, run_demo_smoke
from agent_ledger.ingest.claude_transcripts import ingest as ingest_transcripts
from agent_ledger.ledger.heartbeat import (
    STALE_THRESHOLD_HOURS,
    build_report,
    record_failure,
    record_success,
)
from agent_ledger.ledger.pricing import load_pricing
from agent_ledger.ledger.repository import all_records
from agent_ledger.policy.replay import replay as run_replay
from agent_ledger.recovery.adapters.claude_code import ClaudeCodeAdapter
from agent_ledger.recovery.adapters.codex import CodexAdapter
from agent_ledger.recovery.assembler import recover_session
from agent_ledger.recovery.catalog import RecoveryCatalog
from agent_ledger.recovery.discovery import AdapterRoot, discover_sessions
from agent_ledger.recovery.git_state import resolve_repo
from agent_ledger.recovery.package import (
    assemble_recovery_package,
    recovery_brief_digest,
)
from agent_ledger.recovery.prompt import render_recovery_prompt
from agent_ledger.recovery.receipts import ReceiptStore, run_verification
from agent_ledger.report.spend import per_project
from agent_ledger.resume.detector import detect_ending
from agent_ledger.resume.extractor import extract_packet
from agent_ledger.resume.models import SessionEnding
from agent_ledger.resume.render import render_packet

if TYPE_CHECKING:
    from agent_ledger.recovery.models import RecoveryBrief

app = typer.Typer(help="Local-first LLM cost and routing ledger.")

DEFAULT_DB_PATH = Path("data/ledger.db")
DEFAULT_CONSOLE_PORT = 8680


class RecoveryFormat(StrEnum):
    """Supported non-interactive recovery output formats."""

    json = "json"
    prompt = "prompt"


def _projects_dir() -> Path:
    configured = os.environ.get("AGENT_LEDGER_CLAUDE_PROJECTS_DIR")
    return (
        Path(configured)
        if configured is not None
        else Path("~/.claude/projects").expanduser()
    )


def _codex_sessions_dir() -> Path:
    configured = os.environ.get("AGENT_LEDGER_CODEX_SESSIONS_DIR")
    return (
        Path(configured)
        if configured is not None
        else Path("~/.codex/sessions").expanduser()
    )


def _recovery_roots() -> tuple[AdapterRoot, ...]:
    return (
        AdapterRoot(adapter=ClaudeCodeAdapter(), root=_projects_dir()),
        AdapterRoot(adapter=CodexAdapter(), root=_codex_sessions_dir()),
    )


def _receipt_store() -> ReceiptStore:
    configured = os.environ.get("AGENT_LEDGER_DATA_DIR")
    data_root = (
        Path(configured).expanduser()
        if configured is not None
        else Path("~/.local/share/agent-ledger").expanduser()
    )
    return ReceiptStore(data_root / "recovery-receipts")


def _recovery_catalog(repo: Path) -> RecoveryCatalog:
    trusted_repo = resolve_repo(repo)
    roots = _recovery_roots()
    discovery = discover_sessions(repo=trusted_repo, roots=roots)
    return RecoveryCatalog(
        repo=trusted_repo,
        discovery=discovery,
        adapters=tuple(root.adapter for root in roots),
    )


def _find_transcript(session: str) -> Path:
    projects_dir = _projects_dir()
    if not projects_dir.is_dir():
        raise FileNotFoundError(
            f"Claude projects directory not found at {projects_dir}"
        )
    for path in projects_dir.rglob("*.jsonl"):
        if "subagents" not in path.parts and path.stem == session:
            return path
    raise FileNotFoundError(f"Session {session} not found")


def _serve_console(
    brief: RecoveryBrief,
    prompt: str,
    *,
    port: int,
    open_browser: bool,
) -> None:
    token = secrets.token_urlsafe(24)
    console_app = create_app(
        brief=brief,
        prompt=prompt,
        capability_token=token,
        port=port,
    )
    url = f"http://127.0.0.1:{port}/?token={token}"
    typer.echo(f"Recovery console: {url}")
    typer.echo("Press Ctrl+C to stop the local read-only server.")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(console_app, host="127.0.0.1", port=port, log_level="warning")


def _serve_inbox(
    catalog: RecoveryCatalog,
    *,
    port: int,
    open_browser: bool,
) -> None:
    token = secrets.token_urlsafe(24)
    console_app = create_app(
        catalog=catalog,
        receipt_store=_receipt_store(),
        capability_token=token,
        port=port,
    )
    url = f"http://127.0.0.1:{port}/?token={token}"
    count = len(catalog.public.sessions)
    noun = "session" if count == 1 else "sessions"
    typer.echo(f"Recovery Inbox: {url}")
    typer.echo(f"{count} bound {noun}; {catalog.public.excluded_count} excluded.")
    typer.echo("Press Ctrl+C to stop the local read-only server.")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(console_app, host="127.0.0.1", port=port, log_level="warning")


@app.command()
def ingest(
    source_dir: Path = typer.Argument(..., help="e.g. ~/.claude/projects"),
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Ingest Claude Code transcripts under source_dir into db_path.

    Records a heartbeat row on every run, success or failure (Fix 2,
    2026-08-02) — `agent-ledger doctor` reads these to catch a silent
    collection gap instead of nothing noticing at all.
    """

    try:
        count = ingest_transcripts(source_dir, db_path)
    except (OSError, ValueError, RuntimeError) as exc:
        record_failure(db_path, str(exc))
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    record_success(db_path, count)
    typer.echo(f"Ingested {count} record(s) into {db_path}")


@app.command()
def report(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Print per-project spend."""

    frame = per_project(db_path)
    typer.echo(frame)


@app.command()
def doctor(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Print ledger staleness: newest row age, last heartbeat, recent volume.

    Exits non-zero when the ledger is stale (Fix 2, 2026-08-02) — no rows
    ever, or the newest one older than `STALE_THRESHOLD_HOURS` — so this is
    safe to wire into a shell prompt or cron/launchd check.
    """

    doctor_report = build_report(db_path)

    if doctor_report.newest_row_ts is None:
        typer.echo("Newest row: none — ledger has never been ingested")
    else:
        age = doctor_report.newest_row_age_hours or 0.0
        typer.echo(
            f"Newest row: {doctor_report.newest_row_ts.isoformat()} ({age:.1f}h ago)"
        )
    typer.echo(f"Total rows: {doctor_report.total_rows}")
    typer.echo(f"Rows in last 7 days: {doctor_report.rows_last_7_days}")

    if doctor_report.last_heartbeat_ts is None:
        typer.echo("Last heartbeat: never recorded (no `ingest` run yet)")
    else:
        typer.echo(
            f"Last heartbeat: {doctor_report.last_heartbeat_ts.isoformat()} "
            f"status={doctor_report.last_heartbeat_status}"
        )
        if doctor_report.last_heartbeat_error:
            typer.echo(f"  error: {doctor_report.last_heartbeat_error}")

    if doctor_report.is_stale:
        typer.echo(
            f"STALE: no successful ingest in over {STALE_THRESHOLD_HOURS:.0f}h "
            "— run `agent-ledger ingest ~/.claude/projects`.",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo("OK: ledger is current.")


@app.command()
def replay(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Print the counterfactual-replay ceiling. This is an UPPER BOUND on
    theoretical savings, not a recommendation — see
    agent_ledger.policy.replay's module docstring for exactly what is and
    is not modeled before quoting this number anywhere."""

    records = all_records(db_path)
    prices = load_pricing()
    result = run_replay(records, prices)
    typer.echo(f"Actual spend:              ${result.actual_cost_usd:.4f}")
    typer.echo(f"Downgraded-tier cost:      ${result.downgraded_cost_usd:.4f}")
    typer.echo("Ceiling savings (UPPER BOUND, not a recommendation):")
    typer.echo(f"  ${result.ceiling_savings_usd:.4f}")
    typer.echo(
        f"Modeled: {result.calls_modeled} calls "
        f"({result.modeled_share:.1%}); "
        f"not modeled: {result.calls_not_modeled} calls "
        f"(${result.not_modeled_cost_usd:.4f} of spend, excluded from the ceiling)"
    )


@app.command()
def resume(
    session: str = typer.Option(None, "--session", help="Session ID to resume."),
    project: str = typer.Option(None, "--project", help="Project name."),
    out: Path = typer.Option(None, "--out", help="Path to write the packet."),
    list_sessions: bool = typer.Option(
        False, "--list", help="List sessions with ending classification."
    ),
) -> None:
    """Reconstruct handoff packets or list sessions with ending classification."""

    projects_dir = _projects_dir()

    if not projects_dir.is_dir():
        typer.echo(
            f"Error: Claude projects directory not found at {projects_dir}",
            err=True,
        )
        raise typer.Exit(1)

    transcripts: list[Path] = []
    for p in projects_dir.rglob("*.jsonl"):
        if "subagents" in p.parts:
            continue
        transcripts.append(p)
    if project:
        transcripts = [
            path
            for path in transcripts
            if extract_packet(path).packet.project == project
        ]

    if list_sessions:
        rows = []
        for p in transcripts:
            try:
                ending = detect_ending(p)
                session_id = p.stem
                project_name = p.parent.name
                last_ts = ""

                from agent_ledger.ingest.claude_transcripts import (
                    iter_transcript_lines,
                )

                lines = list(iter_transcript_lines(p))
                if lines:
                    for record in reversed(lines):
                        if "cwd" in record and isinstance(record["cwd"], str):
                            project_name = Path(record["cwd"]).name
                            break
                    for record in reversed(lines):
                        if "timestamp" in record and isinstance(
                            record["timestamp"], str
                        ):
                            last_ts = record["timestamp"]
                            break

                rows.append(
                    {
                        "sessionId": session_id,
                        "project": project_name,
                        "last_activity": last_ts,
                        "ending": ending.value,
                    }
                )
            except Exception:
                pass

        rows.sort(key=lambda r: r["last_activity"], reverse=True)

        if not rows:
            typer.echo("No sessions found.")
            return

        frame = pl.DataFrame(
            rows,
            schema={
                "sessionId": pl.String,
                "project": pl.String,
                "last_activity": pl.String,
                "ending": pl.String,
            },
        )
        typer.echo(frame)
        return

    # Non-list path
    if session:
        # Resume specific session
        target_path = None
        for p in transcripts:
            if p.stem == session:
                target_path = p
                break
        if not target_path:
            typer.echo(f"Error: Session {session} not found.", err=True)
            raise typer.Exit(1)
        typer.echo(f"Resuming specific session: {session}")
    else:
        # Default to most recent non-completed session
        rows_non_completed = []
        for p in transcripts:
            try:
                ending = detect_ending(p)
                if ending == SessionEnding.completed:
                    continue
                last_ts = ""
                from agent_ledger.ingest.claude_transcripts import (
                    iter_transcript_lines,
                )

                lines = list(iter_transcript_lines(p))
                if lines:
                    for record in reversed(lines):
                        if "timestamp" in record and isinstance(
                            record["timestamp"], str
                        ):
                            last_ts = record["timestamp"]
                            break
                rows_non_completed.append((p, last_ts))
            except Exception:
                pass

        rows_non_completed.sort(key=lambda x: x[1], reverse=True)
        if not rows_non_completed:
            typer.echo("No non-completed sessions found to resume.")
            return

        target_path = rows_non_completed[0][0]
        typer.echo(
            f"Most recent non-completed session: {target_path.stem} "
            f"(Last activity: {rows_non_completed[0][1]})"
        )

    result = extract_packet(target_path, ending=detect_ending(target_path))
    rendered = render_packet(result.packet)
    if out is not None:
        out.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote reconstructed resume packet to {out}")
    else:
        typer.echo(rendered, nl=False)


@app.command()
def recover(
    session: str = typer.Option(..., "--session", help="Session ID to recover."),
    repo: Path = typer.Option(
        Path.cwd(),
        "--repo",
        help="Trusted current Git repository.",
    ),
    output_format: RecoveryFormat = typer.Option(
        RecoveryFormat.prompt,
        "--format",
        help="Non-interactive output format.",
    ),
    open_console: bool = typer.Option(
        False,
        "--open",
        help="Open the capability-protected local recovery console.",
    ),
    port: int = typer.Option(
        DEFAULT_CONSOLE_PORT,
        "--port",
        min=1,
        max=65535,
        help="Local console port.",
    ),
) -> None:
    """Recover a session against current, owner-selected repository state."""

    try:
        transcript = _find_transcript(session)
        brief = recover_session(transcript, repo)
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    prompt = render_recovery_prompt(brief)
    if open_console:
        _serve_console(brief, prompt, port=port, open_browser=True)
        return
    if output_format is RecoveryFormat.json:
        typer.echo(json.dumps(brief.model_dump(mode="json"), indent=2))
    else:
        typer.echo(prompt, nl=False)


@app.command()
def console(
    repo: Path = typer.Option(
        Path.cwd(),
        "--repo",
        help="Trusted current Git repository.",
    ),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="Do not open the browser automatically.",
    ),
    port: int = typer.Option(
        DEFAULT_CONSOLE_PORT,
        "--port",
        min=1,
        max=65535,
        help="Local console port.",
    ),
) -> None:
    """Open the repository-bound local Recovery Inbox."""

    try:
        catalog = _recovery_catalog(repo)
    except (OSError, ValueError, RuntimeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _serve_inbox(catalog, port=port, open_browser=not no_open)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def verify(
    context: typer.Context,
    session: str = typer.Option(..., "--session", help="Opaque candidate ID."),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="Trusted Git repository."),
    label: str = typer.Option(..., "--label", help="Untrusted owner annotation."),
    timeout: float = typer.Option(
        300.0,
        "--timeout",
        min=0.1,
        max=3600,
        help="Maximum process duration in seconds.",
    ),
) -> None:
    """Record one explicit owner-supplied process attempt after ``--``."""

    argv = tuple(context.args)
    if argv and argv[0] == "--":
        argv = argv[1:]
    try:
        catalog = _recovery_catalog(repo)
        brief = catalog.recover(session)
        receipt = run_verification(
            repo=catalog.trusted_repo,
            candidate_id=session,
            brief_digest=recovery_brief_digest(brief),
            owner_label=label,
            argv=argv,
            timeout_seconds=timeout,
        )
        path = _receipt_store().save(receipt)
    except (OSError, ValueError, RuntimeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(receipt.model_dump_json(indent=2))
    typer.echo(f"Stored private receipt: {path.name}")


@app.command("package")
def package_command(
    session: str = typer.Option(..., "--session", help="Opaque candidate ID."),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="Trusted Git repository."),
    output: Path = typer.Option(..., "--output", help="Recovery package JSON path."),
) -> None:
    """Export a canonical read-only recovery package."""

    try:
        catalog = _recovery_catalog(repo)
        package = assemble_recovery_package(
            catalog=catalog,
            candidate_id=session,
            store=_receipt_store(),
        )
        output.write_text(package.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Wrote recovery package: {output}")


@app.command()
def demo(
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="Do not open the browser automatically.",
    ),
    smoke: bool = typer.Option(
        False,
        "--smoke",
        help="Start, fetch, stop, clean, and exit.",
    ),
    port: int = typer.Option(
        DEFAULT_CONSOLE_PORT,
        "--port",
        min=0,
        max=65535,
        help="Local demo port; zero selects a free port in smoke mode.",
    ),
) -> None:
    """Run the exact disposable Build Week recovery scenario."""

    demo_root = Path(tempfile.mkdtemp(prefix="agent-ledger-demo-"))
    try:
        if smoke:
            result = run_demo_smoke(base_dir=demo_root, port=port)
            typer.echo(
                "Demo smoke passed: "
                f"root={result.root_status}, api={result.api_status}, "
                f"prompt={result.prompt_status}, stopped={result.server_stopped}"
            )
            return
        if port == 0:
            raise DemoError("port zero is only supported with --smoke")
        scenario = build_demo_scenario(demo_root)
        _serve_console(
            scenario.brief,
            scenario.prompt,
            port=port,
            open_browser=not no_open,
        )
    except (DemoError, OSError, ValueError, RuntimeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        if demo_root.exists():
            shutil.rmtree(demo_root)


if __name__ == "__main__":
    app()
