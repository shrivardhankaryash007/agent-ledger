"""Typer CLI: `agent-ledger ingest` / `agent-ledger report` / `agent-ledger replay`."""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import typer

from agent_ledger.ingest.claude_transcripts import ingest as ingest_transcripts
from agent_ledger.ledger.pricing import load_pricing
from agent_ledger.ledger.repository import all_records
from agent_ledger.policy.replay import replay as run_replay
from agent_ledger.report.spend import per_project
from agent_ledger.resume.detector import detect_ending
from agent_ledger.resume.models import SessionEnding

app = typer.Typer(help="Local-first LLM cost and routing ledger.")

DEFAULT_DB_PATH = Path("data/ledger.db")


@app.command()
def ingest(
    source_dir: Path = typer.Argument(..., help="e.g. ~/.claude/projects"),
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Ingest Claude Code transcripts under source_dir into db_path."""

    count = ingest_transcripts(source_dir, db_path)
    typer.echo(f"Ingested {count} record(s) into {db_path}")


@app.command()
def report(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Print per-project spend."""

    frame = per_project(db_path)
    typer.echo(frame)


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

    projects_dir_str = os.environ.get("AGENT_LEDGER_CLAUDE_PROJECTS_DIR")
    if projects_dir_str:
        projects_dir = Path(projects_dir_str)
    else:
        projects_dir = Path("~/.claude/projects").expanduser()

    if not projects_dir.is_dir():
        typer.echo(
            f"Error: Claude projects directory not found at {projects_dir}",
            err=True,
        )
        raise typer.Exit(1)

    transcripts = []
    for p in projects_dir.rglob("*.jsonl"):
        if "subagents" in p.parts:
            continue
        transcripts.append(p)

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

    typer.echo("Resume-packet generation is not implemented yet (M3.b).")


if __name__ == "__main__":
    app()
