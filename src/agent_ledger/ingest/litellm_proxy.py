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
from typing import Any, cast

from litellm.integrations.custom_logger import CustomLogger

from agent_ledger.ledger.models import CallRecord
from agent_ledger.ledger.pricing import cost_usd, load_pricing
from agent_ledger.ledger.repository import upsert

UNKNOWN_PROJECT = "unknown"


def classify(vendor: str, model: str) -> str:
    """Map (custom_llm_provider, model) to a capability class.

    Mirrors the mapping in ``ingest.claude_transcripts.classify``, but keyed
    off litellm's own ``custom_llm_provider`` instead of guessing the vendor
    from the model string.

    Args:
        vendor: litellm's ``custom_llm_provider`` (e.g. "ollama",
            "anthropic", "openai", "google", "xai").
        model: the provider-prefix-stripped model SKU (e.g. "gemma4:latest").

    Returns:
        A capability-class string: "local_fast", "frontier_deep",
        "coding_strong", or "fast_small".

    Example:
        >>> classify("ollama", "gemma4:latest")
        'local_fast'
        >>> classify("anthropic", "claude-sonnet-4")
        'coding_strong'
    """

    name = model.lower()
    if vendor == "ollama":
        return "local_fast"
    if vendor == "anthropic":
        if "opus" in name or "fable" in name:
            return "frontier_deep"
        if "sonnet" in name:
            return "coding_strong"
        if "haiku" in name:
            return "fast_small"
        return "frontier_deep"
    if vendor == "openai":
        if "codex" in name:
            return "coding_strong"
        return "frontier_deep"
    if vendor == "google":
        return "frontier_deep"
    if vendor == "xai":
        return "frontier_deep"
    return "frontier_deep"


def record_from_event(
    kwargs: dict[str, Any], response_obj: Any, end_time: datetime
) -> CallRecord:
    """Build one CallRecord from a single litellm success-event payload.

    ``model_sku``/``vendor`` come straight off ``kwargs`` (litellm strips the
    provider prefix already, e.g. "gemma4:latest" — matching the plain-name
    convention in ``ledger/pricing.yaml`` and the workspace's
    ``MODEL-PRICING.md``). ``project`` is sourced from
    ``kwargs["litellm_params"]["metadata"]["caller_tag"]``, falling back to
    ``UNKNOWN_PROJECT``. ``session_id`` is ``kwargs["litellm_call_id"]``
    (unique per call; safe as the upsert key alongside ``model_sku`` since
    one call = one row here). Cost prefers litellm's own
    ``response_cost`` when it is a non-``None`` float, otherwise falls back
    to ``ledger.pricing.cost_usd()`` against ``pricing.yaml``.

    Args:
        kwargs: litellm's success-event kwargs payload (see module docstring
            and docs/architecture.md § M1 for the verified real shape).
        response_obj: litellm's response object; must expose
            ``usage.prompt_tokens`` / ``usage.completion_tokens``.
        end_time: the call's completion timestamp, used as ``CallRecord.ts``.

    Returns:
        One populated CallRecord representing this single live call.

    Raises:
        ValueError: if no cost is reported by litellm and the model has no
            entry in the local pricing table either.

    Example:
        >>> kwargs = {
        ...     "model": "gemma4:latest",
        ...     "custom_llm_provider": "ollama",
        ...     "litellm_call_id": "abc-123",
        ...     "litellm_params": {"metadata": {"caller_tag": "my-project"}},
        ...     "response_cost": 0.0,
        ... }
        >>> from types import SimpleNamespace
        >>> from datetime import datetime, UTC
        >>> response_obj = SimpleNamespace(
        ...     usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)
        ... )
        >>> record = record_from_event(kwargs, response_obj, datetime.now(UTC))
        >>> record.project
        'my-project'
    """

    model_sku = cast("str", kwargs["model"])
    vendor = cast("str", kwargs["custom_llm_provider"])
    litellm_params = cast("dict[str, Any]", kwargs.get("litellm_params") or {})
    metadata = cast("dict[str, Any]", litellm_params.get("metadata") or {})
    project = metadata.get("caller_tag") or UNKNOWN_PROJECT
    session_id = cast("str", kwargs["litellm_call_id"])
    capability_class = classify(vendor, model_sku)
    in_tokens = int(response_obj.usage.prompt_tokens)
    out_tokens = int(response_obj.usage.completion_tokens)

    reported_cost = kwargs.get("response_cost")
    cost: float
    if isinstance(reported_cost, float):
        cost = reported_cost
    else:
        prices = load_pricing()
        if model_sku not in prices:
            raise ValueError(f"no pricing configured for litellm model {model_sku!r}")
        cost = cost_usd(model_sku, in_tokens, out_tokens, prices)

    return CallRecord(
        ts=end_time,
        session_id=session_id,
        project=project,
        model_sku=model_sku,
        capability_class=capability_class,
        vendor=vendor,
        in_tokens=in_tokens,
        out_tokens=out_tokens,
        cost_usd=cost,
        calls=1,
    )


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
