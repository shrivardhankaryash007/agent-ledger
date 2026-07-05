"""Typer CLI: `agent-ledger ingest` / `agent-ledger report` / `agent-ledger replay`."""

from __future__ import annotations

from pathlib import Path

import typer

from agent_ledger.ingest.claude_transcripts import ingest as ingest_transcripts
from agent_ledger.ledger.pricing import load_pricing
from agent_ledger.ledger.repository import all_records
from agent_ledger.policy.replay import replay as run_replay
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


if __name__ == "__main__":
    app()
