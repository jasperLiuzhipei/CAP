from __future__ import annotations

from datetime import datetime
from typing import Any

from copilot_agent.model_registry import (
    ModelPricing,
    default_pricing_table,
    get_model_pricing,
)

from .models import CostEstimate, RunEvent, TokenUsage

DEFAULT_MODEL_PRICING = default_pricing_table()

TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}


def extract_usage_from_payload(payload: dict[str, Any] | None) -> TokenUsage:
    payload = payload or {}
    usage = payload.get("usage", payload)
    if not isinstance(usage, dict):
        return TokenUsage()
    input_tokens = _optional_int(usage.get("input_tokens"))
    output_tokens = _optional_int(usage.get("output_tokens"))
    total_tokens = _optional_int(usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return TokenUsage(
        requests=_optional_int(usage.get("requests")),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def latest_usage_event(events: list[RunEvent]) -> TokenUsage:
    for event in reversed(events):
        if event.event_type == "model.usage":
            return extract_usage_from_payload(event.payload)
    return TokenUsage()


def estimate_cost(
    *,
    provider: str,
    model: str,
    usage: TokenUsage,
    pricing: dict[tuple[str, str], ModelPricing] | None = None,
) -> CostEstimate:
    if pricing is None:
        model_pricing = get_model_pricing(provider, model)
    else:
        model_pricing = pricing.get((provider.lower(), model.lower()))
    if model_pricing is None:
        return CostEstimate(pricing_source="pricing_unavailable")
    if usage.input_tokens is None and usage.output_tokens is None:
        return CostEstimate(pricing_source="usage_unavailable")

    input_cost = _token_cost(
        usage.input_tokens,
        model_pricing.input_usd_per_million_tokens,
    )
    output_cost = _token_cost(
        usage.output_tokens,
        model_pricing.output_usd_per_million_tokens,
    )
    total_cost = None
    if input_cost is not None or output_cost is not None:
        total_cost = round((input_cost or 0.0) + (output_cost or 0.0), 8)
    return CostEstimate(
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=total_cost,
        pricing_source=model_pricing.source,
        estimated=True,
    )


def duration_ms(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
        finished = datetime.fromisoformat(finished_at)
    except ValueError:
        return None
    return max(0.0, (finished - started).total_seconds() * 1000)


def started_at_from_events(events: list[RunEvent]) -> str | None:
    for event in events:
        if event.event_type == "run.started":
            return event.created_at
    return None


def finished_at_from_events(events: list[RunEvent]) -> str | None:
    for event in reversed(events):
        if event.event_type in TERMINAL_EVENTS:
            return event.created_at
    return None


def failed_reason_from_events(events: list[RunEvent], summary: str) -> str | None:
    for event in reversed(events):
        if event.event_type == "policy.violation":
            reason = event.payload.get("reason")
            return str(reason) if reason else "policy violation"
    for event in reversed(events):
        if event.event_type == "run.failed":
            reason = event.payload.get("summary") or event.payload.get("error")
            return str(reason) if reason else summary or "run failed"
    return summary or None


def usage_to_payload(usage: TokenUsage) -> dict[str, int]:
    payload: dict[str, int] = {}
    for key, value in (
        ("requests", usage.requests),
        ("input_tokens", usage.input_tokens),
        ("output_tokens", usage.output_tokens),
        ("total_tokens", usage.total_tokens),
    ):
        if value is not None:
            payload[key] = value
    return payload


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _token_cost(tokens: int | None, usd_per_million: float) -> float | None:
    if tokens is None:
        return None
    return round(tokens / 1_000_000 * usd_per_million, 8)
