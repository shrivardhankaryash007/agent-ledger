"""Core domain model. Frozen shape per AGENTS.md rule 1 — change only via a
version bump + migration."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, NonNegativeInt

MODEL_VERSION = 1


class CallRecord(BaseModel):
    """One aggregated (session, model) usage bucket attributed to a project."""

    model_version: int = MODEL_VERSION
    ts: datetime
    session_id: str
    project: str
    model_sku: str
    capability_class: str
    vendor: str
    in_tokens: NonNegativeInt
    out_tokens: NonNegativeInt
    cost_usd: float = Field(ge=0.0)
    calls: NonNegativeInt
