"""Persist normalized traces received through OTLP/HTTP JSON."""

from __future__ import annotations

from typing import Any, Protocol

from agentgate.domain import Trace
from agentgate.trace.normalizer import normalize_otlp_json


class TraceSink(Protocol):
    def save_trace(self, trace: Trace) -> None: ...


def ingest_otlp_http_json(payload: dict[str, Any], sink: TraceSink) -> int:
    """Normalize and persist one OTLP JSON payload, returning its Span count."""

    if not isinstance(payload, dict):
        raise ValueError("OTLP payload must be an object")
    if not isinstance(payload.get("resourceSpans", []), list):
        raise ValueError("resourceSpans must be an array")
    traces = normalize_otlp_json(payload)
    for trace in traces:
        sink.save_trace(trace)
    return sum(len(trace.spans) for trace in traces)
