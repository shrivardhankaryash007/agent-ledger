"""Pydantic models and schemas for Resume Packet."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SessionEnding(StrEnum):
    completed = "completed"
    interrupted_limit = "interrupted_limit"
    interrupted_abort = "interrupted_abort"
    unknown = "unknown"


PACKET_VERSION = 1


class ResumePacket(BaseModel):
    """Pydantic model representing a session resume packet (v1)."""

    packet_version: int = PACKET_VERSION
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str
    project: str
    provider: str
    model_skus: list[str]
    started: datetime
    last_activity: datetime
    ending: SessionEnding
    in_tokens: int
    out_tokens: int
    intent: str
    touched_files: list[str]
    bash_commands: list[str]
    last_state: str
    git_status: str
    next_actions: list[str]
    source_path: str
