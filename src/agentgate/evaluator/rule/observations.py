"""Extract deterministic Rule observations from normalized Traces."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, TypeAlias

from agentgate.domain import (
    OutputExpectation,
    StateExpectation,
    ToolArgumentExpectation,
    Trace,
)


_SPAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


class _MissingValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Final = _MissingValue()

ObservableExpectation: TypeAlias = (
    StateExpectation | OutputExpectation | ToolArgumentExpectation
)


@dataclass(frozen=True, slots=True)
class Observation:
    """Values extracted for a Rule with aligned Trace Span references."""

    values: tuple[Any, ...]
    span_ids: tuple[str | None, ...]

    def __post_init__(self) -> None:
        if len(self.values) != len(self.span_ids):
            raise ValueError("Observation values and span_ids must have equal lengths")
        if any(
            span_id is not None and not _SPAN_ID_PATTERN.fullmatch(span_id)
            for span_id in self.span_ids
        ):
            raise ValueError("Observation span_ids must be lowercase OTel Span IDs")


def value_at_path(data: Any, path: str | None) -> Any:
    """Return one dotted-path value, the root value, or the missing sentinel."""

    if path is None:
        return data
    parts = path.split(".")
    if not path.strip() or any(not part.strip() for part in parts):
        raise ValueError("observation path must contain nonblank dotted segments")

    current = data
    for part in parts:
        if not isinstance(current, Mapping) or part not in current:
            return MISSING
        current = current[part]
    return current


def observe_expectation(
    trace: Trace,
    expectation: ObservableExpectation,
) -> Observation:
    """Extract values and evidence locations for one supported expectation."""

    if isinstance(expectation, StateExpectation):
        state_spans = (
            span for span in trace.spans if span.operation_type == "state"
        )
        span = max(state_spans, key=lambda item: item.sequence, default=None)
        return Observation(
            values=(value_at_path(trace.final_state, expectation.path),),
            span_ids=(span.span_id if span else None,),
        )

    if isinstance(expectation, OutputExpectation):
        return Observation(
            values=(value_at_path(trace.final_output, expectation.path),),
            span_ids=(None,),
        )

    if isinstance(expectation, ToolArgumentExpectation):
        spans = sorted(
            (
                span
                for span in trace.spans
                if span.operation_type == "tool" and span.name == expectation.tool
            ),
            key=lambda item: item.sequence,
        )
        if expectation.occurrence == "first":
            spans = spans[:1]
        elif expectation.occurrence == "last":
            spans = spans[-1:]
        return Observation(
            values=tuple(
                value_at_path(span.attributes, expectation.path) for span in spans
            ),
            span_ids=tuple(span.span_id for span in spans),
        )

    raise TypeError(f"unsupported expectation: {type(expectation).__name__}")
