"""Typer CLI: `agent-ledger ingest` / `agent-ledger report`."""

from __future__ import annotations

from pathlib import Path

import typer

from agent_ledger.ingest.claude_transcripts import ingest as ingest_transcripts
from agent_ledger.report.spend import per_project

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


if __name__ == "__main__":
    app()
