"""Extract values from canonical traces without conflating null and missing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentgate.domain import OutputExpectation, StateExpectation, ToolArgumentExpectation, Trace

from .models import Observation


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


def value_at(data: Any, path: str | None) -> Any:
    if path is None or path == "":
        return data
    current = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return MISSING
        current = current[part]
    return current


def observe(trace: Trace, expectation: Any) -> Observation:
    if isinstance(expectation, StateExpectation):
        span = next((item for item in reversed(trace.spans) if item.operation_type == "state"), None)
        return Observation(
            values=(value_at(trace.final_state, expectation.path),),
            span_ids=(span.span_id if span else None,),
        )
    if isinstance(expectation, OutputExpectation):
        return Observation(values=(value_at(trace.final_output, expectation.path),), span_ids=(None,))
    if isinstance(expectation, ToolArgumentExpectation):
        spans = [
            item for item in trace.spans
            if item.operation_type == "tool" and item.name == expectation.tool
        ]
        if not spans:
            return Observation(values=(), span_ids=())
        if expectation.occurrence == "first":
            spans = spans[:1]
        elif expectation.occurrence == "last":
            spans = spans[-1:]
        return Observation(
            values=tuple(value_at(span.attributes, expectation.path) for span in spans),
            span_ids=tuple(span.span_id for span in spans),
        )
    raise TypeError(f"unsupported expectation: {type(expectation).__name__}")


def condition_operator(condition: Any) -> str:
    return {
        "equals": "equals",
        "within_tolerance": "within_tolerance",
        "within_range": "within_range",
        "matches_pattern": "matches_pattern",
        "one_of": "is_one_of",
        "must_be_missing": "must_be_missing",
        "matches_json_schema": "matches_json_schema",
    }[condition.kind]
