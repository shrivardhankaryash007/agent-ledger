"""M1 ingest source: a litellm CustomLogger callback for live capture.

Registered via ``litellm.callbacks = [AgentLedgerLoggerCallback(db_path)]``
on any process that calls ``litellm.completion(...)``. Each call becomes one
CallRecord — unlike the M0 transcript source (which aggregates many lines
into one record per session+model), a live call is already one atomic
event, so ``session_id`` here is the call's own ``litellm_call_id`` and
``calls`` is always 1.

Verified against the installed litellm's actual callback shape (not the
stale/guessed public docs) by running a real completion through Ollama and
inspecting `kwargs`/`response_obj` directly — see
docs/architecture.md § M1 for the captured shapes. Independent of
`~/dev/scripts/token_ledger.py` / `ide_meter.py` by design — see
AGENTS.md rule 2.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.pricing import cost_usd, load_pricing
from agent_ledger.ledger.repository import upsert

UNKNOWN_PROJECT = "unknown"


def classify(vendor: str, model: str) -> str:
    """Map (custom_llm_provider, model) to a capability class.

    M1 TODO: ollama -> "local_fast"; anthropic/openai/google/xai -> the
    same capability-class mapping already proven in
    ingest.claude_transcripts.classify, applied to the vendor string
    litellm reports directly instead of substring-matching the model name.
    """

    raise NotImplementedError("M1: implement classify()")


def record_from_event(
    kwargs: dict[str, Any], response_obj: Any, end_time: datetime
) -> CallRecord:
    """Build one CallRecord from a single litellm success-event payload.

    M1 TODO:
    - model_sku = kwargs["model"] (already provider-prefix-stripped by
      litellm, e.g. "gemma4:latest" — matches the existing plain-name
      convention in ledger/pricing.yaml and workspace MODEL-PRICING.md).
    - vendor = kwargs["custom_llm_provider"].
    - project = kwargs["litellm_params"]["metadata"].get("caller_tag") or
      UNKNOWN_PROJECT.
    - session_id = kwargs["litellm_call_id"] (unique per call; safe as the
      upsert key alongside model_sku since one call = one row here).
    - in_tokens/out_tokens = response_obj.usage.prompt_tokens /
      .completion_tokens.
    - cost_usd: prefer kwargs.get("response_cost") when it is a non-None
      float (litellm's own maintained pricing DB); otherwise fall back to
      ledger.pricing.cost_usd() against pricing.yaml, raising the same
      "no pricing configured" error as M0 if the model is in neither.
    - calls = 1.
    """

    raise NotImplementedError("M1: implement record_from_event()")


class AgentLedgerLoggerCallback(CustomLogger):
    """Registers as ``litellm.callbacks = [AgentLedgerLoggerCallback(path)]``."""

    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.db_path = db_path

    def log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        record = record_from_event(kwargs, response_obj, end_time)
        upsert(self.db_path, record)

    async def async_log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        self.log_success_event(kwargs, response_obj, start_time, end_time)


__all__ = [
    "AgentLedgerLoggerCallback",
    "classify",
    "record_from_event",
    "load_pricing",
    "cost_usd",
]
