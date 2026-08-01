"""Core domain model. Frozen shape per AGENTS.md rule 1 — change only via a
version bump + migration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, NonNegativeInt

MODEL_VERSION = 2

# 'git': repo_name resolved via git. 'not_a_repo': cwd_raw resolved to a real
# path that git rejected. 'unknown': no cwd was available to resolve, or a
# source (e.g. M1 live capture) does not attempt git resolution at all.
LabelSource = Literal["git", "not_a_repo", "unknown"]


class CallRecord(BaseModel):
    """One aggregated (session, model) usage bucket attributed to a project.

    ``project`` stays the stable, always-populated grouping key existing
    reports rely on (``repo_name`` when git resolution succeeds, else
    ``"unknown"``). ``repo_name``/``worktree_name``/``branch``/``cwd_raw``/
    ``label_source`` are additive v2 fields (fix spec 2026-08-02): a session
    run inside a git worktree rolls up to its parent ``repo_name`` via
    ``git rev-parse --git-common-dir``, distinct from the ``worktree_name``
    it was actually checked out in. All five are ``None`` for sources that
    never attempt cwd-based git resolution (e.g. M1 live capture, which
    attributes via an explicit caller tag instead).
    """

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
    repo_name: str | None = None
    worktree_name: str | None = None
    branch: str | None = None
    cwd_raw: str | None = None
    label_source: LabelSource | None = None
