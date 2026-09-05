"""Normalize OTLP/HTTP JSON into AgentGate domain traces."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agentgate.domain import SpanStatus, Trace, TraceSpan


def otlp_value(value: dict[str, Any]) -> Any:
    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return value["boolValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "arrayValue" in value:
        return [otlp_value(item) for item in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        return attributes(value["kvlistValue"].get("values", []))
    return None


def attributes(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {item["key"]: otlp_value(item.get("value", {})) for item in items}


def _timestamp(nanoseconds: str | int | None, fallback: datetime) -> datetime:
    if nanoseconds in (None, ""):
        return fallback
    return datetime.fromtimestamp(int(nanoseconds) / 1_000_000_000, tz=UTC)


def _status(raw: dict[str, Any]) -> SpanStatus:
    code = str(raw.get("code", "unset")).lower()
    if code in {"2", "status_code_error", "error"}:
        return SpanStatus.ERROR
    if code in {"1", "status_code_ok", "ok"}:
        return SpanStatus.OK
    return SpanStatus.UNSET


def _events(items: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple({
        "name": item.get("name", "event"),
        "time_unix_nano": item.get("timeUnixNano"),
        "attributes": attributes(item.get("attributes", [])),
    } for item in items)


def normalize_otlp_json(payload: dict[str, Any]) -> tuple[Trace, ...]:
    grouped: dict[tuple[str, str, str], list[TraceSpan]] = defaultdict(list)
    for resource_span in payload.get("resourceSpans", []):
        resource_attrs = attributes(
            resource_span.get("resource", {}).get("attributes", [])
        )
        scope_spans = resource_span.get(
            "scopeSpans", resource_span.get("instrumentationLibrarySpans", [])
        )
        for scope_span in scope_spans:
            for raw in scope_span.get("spans", []):
                span_attrs = {
                    **resource_attrs,
                    **attributes(raw.get("attributes", [])),
                }
                run_id = str(span_attrs.get("agentgate.run_id", "otlp-external"))
                case_id = str(span_attrs.get("agentgate.case_id", "external-trace"))
                trace_id = str(raw.get("traceId") or uuid4().hex)
                span_id = str(raw.get("spanId") or uuid4().hex[:16])
                operation_type = str(
                    span_attrs.get("gen_ai.operation.name")
                    or span_attrs.get("agentgate.operation_type")
                    or "event"
                )
                sequence = len(grouped[(run_id, case_id, trace_id)])
                now = datetime.now(UTC)
                started_at = _timestamp(raw.get("startTimeUnixNano"), now)
                ended_at = _timestamp(raw.get("endTimeUnixNano"), started_at)
                grouped[(run_id, case_id, trace_id)].append(TraceSpan(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=raw.get("parentSpanId") or None,
                    name=raw.get("name", "otlp-span"),
                    operation_type=operation_type,
                    sequence=sequence,
                    started_at=started_at,
                    ended_at=ended_at,
                    status=_status(raw.get("status", {})),
                    attributes=span_attrs,
                    events=_events(raw.get("events", [])),
                ))
    return tuple(
        Trace(trace_id=trace_id, run_id=run_id, case_id=case_id, spans=tuple(spans))
        for (run_id, case_id, trace_id), spans in grouped.items()
    )
