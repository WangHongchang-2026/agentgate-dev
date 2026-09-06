"""Capture local OpenTelemetry spans and resolve completed AgentGate traces."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanContext, StatusCode, Tracer

from agentgate.domain import SpanStatus, Trace, TraceSpan
from agentgate.run.target_protocol import CaseExecutionRequest, CaseExecutionResult
from agentgate.trace.normalizer import assemble_trace, normalize_span


class InMemoryTraceCapture:
    """Own a private OTel provider for deterministic local Trace capture."""

    def __init__(self, *, max_spans: int = 1_000) -> None:
        if max_spans <= 0:
            raise ValueError("max_spans must be greater than zero")
        self._exporter = InMemorySpanExporter(max_spans=max_spans)
        self._provider = TracerProvider(
            resource=Resource.create({"service.name": "agentgate-local-target"})
        )
        self._provider.add_span_processor(SimpleSpanProcessor(self._exporter))

    def get_tracer(self, name: str, version: str | None = None) -> Tracer:
        """Return a tracer from this capture's private provider."""

        if not name.strip():
            raise ValueError("tracer name must not be blank")
        return self._provider.get_tracer(name, version)

    def resolve(
        self,
        request: CaseExecutionRequest,
        result: CaseExecutionResult,
    ) -> Trace:
        """Resolve one completed execution and clear all locally captured spans."""

        try:
            expected_trace_id = request.traceparent.split("-")[1]
            if result.execution_id != request.execution_id:
                raise ValueError("Target result execution_id does not match request")
            if result.trace_id != expected_trace_id:
                raise ValueError("Target result trace_id does not match request traceparent")
            if result.inline_trace is not None:
                raise ValueError("in-memory capture does not accept an inline Trace")

            self._provider.force_flush()
            sdk_spans = tuple(
                span
                for span in self._exporter.get_finished_spans()
                if _trace_id(span.context) == result.trace_id
            )
            if not sdk_spans:
                raise ValueError("no completed spans found for Target result trace_id")
            execution_ids = {
                span.attributes["agentgate.execution.id"]
                for span in sdk_spans
                if "agentgate.execution.id" in span.attributes
            }
            if execution_ids != {request.execution_id}:
                raise ValueError("captured Trace does not match Case execution_id")
            return assemble_trace(tuple(_normalize_sdk_span(span) for span in sdk_spans))
        finally:
            self.clear()

    def clear(self) -> None:
        """Discard all finished spans captured by this instance."""

        self._exporter.clear()

    def shutdown(self) -> None:
        """Shut down this capture's private provider."""

        self._provider.shutdown()


def _normalize_sdk_span(span: ReadableSpan) -> TraceSpan:
    context = _require_context(span.context)
    if span.start_time is None or span.end_time is None:
        raise ValueError("captured Span must have start and end timestamps")
    attributes = {
        **_plain_attributes(span.resource.attributes),
        **_plain_attributes(span.attributes),
    }
    events = tuple(
        {
            "name": event.name,
            "time_unix_nano": event.timestamp,
            "attributes": _plain_attributes(event.attributes),
        }
        for event in span.events
    )
    return normalize_span(
        trace_id=_trace_id(context),
        span_id=f"{context.span_id:016x}",
        parent_span_id=_parent_span_id(span.parent),
        name=span.name,
        started_at=_timestamp(span.start_time),
        ended_at=_timestamp(span.end_time),
        status=_span_status(span.status.status_code),
        attributes=attributes,
        events=events,
    )


def _require_context(context: SpanContext | None) -> SpanContext:
    if context is None or not context.is_valid:
        raise ValueError("captured Span requires a valid OTel SpanContext")
    return context


def _trace_id(context: SpanContext | None) -> str:
    return f"{_require_context(context).trace_id:032x}"


def _parent_span_id(parent: SpanContext | None) -> str | None:
    if parent is None:
        return None
    return f"{parent.span_id:016x}" if parent.is_valid else None


def _timestamp(nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(nanoseconds / 1_000_000_000, tz=UTC)


def _span_status(status: StatusCode) -> SpanStatus:
    if status is StatusCode.ERROR:
        return SpanStatus.ERROR
    if status is StatusCode.OK:
        return SpanStatus.OK
    return SpanStatus.UNSET


def _plain_attributes(values: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(values or {})
