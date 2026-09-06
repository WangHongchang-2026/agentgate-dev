"""Normalize OpenTelemetry data into complete AgentGate Trace objects."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from agentgate.domain import SpanStatus, Trace, TraceSpan


_ATTRIBUTE_ALIASES = {
    "agentgate.run.id": ("agentgate.run_id",),
    "agentgate.case.id": ("agentgate.case_id",),
    "agentgate.turn.id": ("turn_id",),
    "agentgate.operation.type": ("agentgate.operation_type",),
}


def otlp_value(value: dict[str, Any]) -> Any:
    """Decode one OTLP JSON AnyValue."""

    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return value["boolValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "arrayValue" in value:
        return tuple(otlp_value(item) for item in value["arrayValue"].get("values", []))
    if "kvlistValue" in value:
        return attributes(value["kvlistValue"].get("values", []))
    return None


def attributes(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Decode OTLP attributes while rejecting duplicate keys."""

    result: dict[str, Any] = {}
    for item in items:
        key = item.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("OTLP attribute key must be a nonblank string")
        if key in result:
            raise ValueError(f"duplicate OTLP attribute: {key}")
        result[key] = otlp_value(item.get("value", {}))
    return result


def _canonicalize_attributes(values: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(values)
    for canonical, aliases in _ATTRIBUTE_ALIASES.items():
        present = [(key, values[key]) for key in (canonical, *aliases) if key in values]
        if len({json.dumps(value, sort_keys=True) for _, value in present}) > 1:
            raise ValueError(f"conflicting Trace attribute aliases for {canonical}")
        if present:
            normalized[canonical] = present[0][1]
        for alias in aliases:
            normalized.pop(alias, None)
    return normalized


def _timestamp(nanoseconds: str | int | None, field_name: str) -> datetime:
    if nanoseconds in (None, ""):
        raise ValueError(f"OTLP Span requires {field_name}")
    value = int(nanoseconds)
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)


def _status(raw: dict[str, Any]) -> SpanStatus:
    code = str(raw.get("code", "unset")).lower()
    if code in {"2", "status_code_error", "error"}:
        return SpanStatus.ERROR
    if code in {"1", "status_code_ok", "ok"}:
        return SpanStatus.OK
    return SpanStatus.UNSET


def _events(items: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "name": item.get("name", "event"),
            "time_unix_nano": item.get("timeUnixNano"),
            "attributes": attributes(item.get("attributes", [])),
        }
        for item in items
    )


def normalize_span(
    *,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    name: str,
    started_at: datetime,
    ended_at: datetime,
    status: SpanStatus,
    attributes: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]] = (),
) -> TraceSpan:
    """Normalize one source-neutral OTel Span representation."""

    span_attributes = _canonicalize_attributes(attributes)
    operation_type = str(
        span_attributes.get("agentgate.operation.type")
        or span_attributes.get("gen_ai.operation.name")
        or "event"
    )
    return TraceSpan(
        trace_id=trace_id.lower(),
        span_id=span_id.lower(),
        parent_span_id=parent_span_id.lower() if parent_span_id else None,
        name=name,
        operation_type=operation_type,
        sequence=0,
        started_at=started_at,
        ended_at=ended_at,
        status=status,
        attributes=span_attributes,
        events=tuple(dict(event) for event in events),
    )


def _required_owner(spans: Sequence[TraceSpan], key: str) -> str:
    values = {span.attributes.get(key) for span in spans}
    if len(values) != 1:
        raise ValueError(f"Trace Spans contain conflicting {key}")
    value = values.pop()
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Trace Spans require {key}")
    return value


def _json_object(span: TraceSpan, key: str) -> dict[str, Any]:
    raw = span.attributes.get(key)
    if not isinstance(raw, str):
        raise ValueError(f"completion Span requires JSON string attribute {key}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"completion Span contains invalid JSON in {key}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"completion Span attribute {key} must contain a JSON object")
    return value


def assemble_trace(spans: Sequence[TraceSpan]) -> Trace:
    """Build one complete Trace from normalized Spans of one OTel trace."""

    if not spans:
        raise ValueError("cannot assemble an empty Trace")
    trace_ids = {span.trace_id for span in spans}
    if len(trace_ids) != 1:
        raise ValueError("Trace Spans must share one trace_id")

    run_id = _required_owner(spans, "agentgate.run.id")
    case_id = _required_owner(spans, "agentgate.case.id")
    ordered = sorted(spans, key=lambda span: (span.started_at, span.ended_at, span.span_id))
    completion = tuple(
        span
        for span in ordered
        if span.attributes.get("agentgate.trace.complete") is True
    )
    if len(completion) != 1:
        raise ValueError("Trace requires exactly one completion Span")

    turn_outcomes: dict[str, dict[str, Any]] = {}
    for span in ordered:
        if span.attributes.get("agentgate.turn.complete") is not True:
            continue
        turn_id = span.attributes.get("agentgate.turn.id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise ValueError("Turn completion Span requires agentgate.turn.id")
        if turn_id in turn_outcomes:
            raise ValueError(f"duplicate Turn completion Span: {turn_id}")
        turn_outcomes[turn_id] = {
            "input": _json_object(span, "agentgate.turn.input"),
            "output": _json_object(span, "agentgate.turn.output"),
            "state": _json_object(span, "agentgate.turn.state"),
        }
    if not turn_outcomes:
        raise ValueError("Trace requires at least one completed Turn")

    sequenced = tuple(
        span.model_copy(update={"sequence": sequence})
        for sequence, span in enumerate(ordered)
    )
    terminal = completion[0]
    return Trace(
        trace_id=trace_ids.pop(),
        run_id=run_id,
        case_id=case_id,
        spans=sequenced,
        turn_outcomes=turn_outcomes,
        final_output=_json_object(terminal, "agentgate.final.output"),
        final_state=_json_object(terminal, "agentgate.final.state"),
    )


def normalize_otlp_json(payload: dict[str, Any]) -> tuple[Trace, ...]:
    """Normalize a complete OTLP/HTTP JSON payload into completed Traces."""

    if not isinstance(payload, dict):
        raise ValueError("OTLP payload must be an object")
    resources = payload.get("resourceSpans", [])
    if not isinstance(resources, list):
        raise ValueError("resourceSpans must be an array")

    grouped: dict[str, list[TraceSpan]] = defaultdict(list)
    for resource_span in resources:
        resource_attributes = attributes(
            resource_span.get("resource", {}).get("attributes", [])
        )
        scope_spans = resource_span.get(
            "scopeSpans", resource_span.get("instrumentationLibrarySpans", [])
        )
        if not isinstance(scope_spans, list):
            raise ValueError("scopeSpans must be an array")
        for scope_span in scope_spans:
            raw_spans = scope_span.get("spans", [])
            if not isinstance(raw_spans, list):
                raise ValueError("spans must be an array")
            for raw in raw_spans:
                span_attributes = {
                    **resource_attributes,
                    **attributes(raw.get("attributes", [])),
                }
                trace_id = raw.get("traceId")
                span_id = raw.get("spanId")
                if not isinstance(trace_id, str) or not isinstance(span_id, str):
                    raise ValueError("OTLP Span requires traceId and spanId")
                span = normalize_span(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=raw.get("parentSpanId") or None,
                    name=raw.get("name", "otlp-span"),
                    started_at=_timestamp(raw.get("startTimeUnixNano"), "startTimeUnixNano"),
                    ended_at=_timestamp(raw.get("endTimeUnixNano"), "endTimeUnixNano"),
                    status=_status(raw.get("status", {})),
                    attributes=span_attributes,
                    events=_events(raw.get("events", [])),
                )
                grouped[span.trace_id].append(span)

    return tuple(assemble_trace(grouped[trace_id]) for trace_id in sorted(grouped))
