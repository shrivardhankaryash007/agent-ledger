"""Markdown renderer for reconstructed resume packets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_ledger.ingest.claude_transcripts import classify

if TYPE_CHECKING:
    from datetime import datetime

    from agent_ledger.resume.models import ResumePacket


def _format_timestamp(value: datetime) -> str:
    """Format a packet datetime in the session-log schema's UTC form."""

    return value.strftime("%Y-%m-%d %H:%M UTC")


def _bullets(values: list[str], empty_message: str) -> str:
    """Render values as a markdown list with a reconstructive fallback."""

    if not values:
        return f"- {empty_message}"
    return "\n".join(f"- {value}" for value in values)


def render_packet(packet: ResumePacket) -> str:
    """Render a packet in the exact HANDOFF-CONTRACT session-log section schema.

    Args:
        packet: Reconstructed, local-only resume data.

    Returns:
        Machine-readable session-log markdown with a resume header.
    """

    model_class = "coding_strong"
    if packet.model_skus:
        model_class = classify(packet.model_skus[0])[0]
    return "\n".join(
        [
            "---",
            f"session_id: {packet.session_id}",
            f"provider: {packet.provider}",
            f"model_class: {model_class}",
            "phase: other",
            f"project: {packet.project}",
            f"started: {_format_timestamp(packet.started)}",
            f"ended: {_format_timestamp(packet.last_activity)}",
            "---",
            "",
            "> **Resume header:** Reconstructed from local transcript artifacts, "
            "not a graceful session-end log.",
            "",
            "## Intent",
            packet.intent,
            "",
            "## Touched",
            _bullets(
                packet.touched_files, "No file-changing tool use was recoverable."
            ),
            "",
            "## Verified",
            "- Reconstructed from transcript; no post-interruption verification "
            "was recorded.",
            "",
            "## Decisions",
            f"- Packet ending classified as {packet.ending.value}.",
            f"- Git status: {packet.git_status}",
            "",
            "## Token Cost",
            f"- {model_class}: {packet.in_tokens} in / {packet.out_tokens} out / "
            "unavailable (reconstructed transcript totals)",
            "",
            "## Residual Risk",
            "- Reconstructed packet: inspect the working tree and rerun the "
            "relevant checks before relying on recorded state.",
            "",
            "## Handoff Note",
            f"Last recorded state: {packet.last_state}",
            "",
            "Next actions:",
            _bullets(
                packet.next_actions,
                "Inspect the transcript and working tree before resuming work.",
            ),
            "",
        ]
    )
