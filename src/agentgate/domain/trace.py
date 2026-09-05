"""Normalized execution traces used by AgentGate evaluators."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import DomainModel, FrozenJsonObject, normalize_utc, require_non_blank, utcnow


_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


class SpanStatus(StrEnum):
    """Normalized completion status independent of an observability vendor."""

    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


class TraceSpan(DomainModel):
    """One normalized OTel-shaped operation within an Agent execution."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    operation_type: str
    sequence: int = Field(ge=0)
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime = Field(default_factory=utcnow)
    status: SpanStatus = SpanStatus.UNSET
    attributes: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    events: tuple[FrozenJsonObject, ...] = ()

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, value: str) -> str:
        if not _TRACE_ID_PATTERN.fullmatch(value):
            raise ValueError("trace_id must be exactly 32 lowercase hexadecimal characters")
        return value

    @field_validator("span_id", "parent_span_id")
    @classmethod
    def validate_span_id(cls, value: str | None) -> str | None:
        if value is not None and not _SPAN_ID_PATTERN.fullmatch(value):
            raise ValueError("span ids must be exactly 16 lowercase hexadecimal characters")
        return value

    @field_validator("name", "operation_type")
    @classmethod
    def validate_non_blank(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"TraceSpan {info.field_name}")

    @field_validator("started_at", "ended_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime, info: ValidationInfo) -> datetime:
        return normalize_utc(value, f"TraceSpan {info.field_name}")

    @model_validator(mode="after")
    def validate_timing(self) -> "TraceSpan":
        if self.ended_at < self.started_at:
            raise ValueError("TraceSpan ended_at must not be before started_at")
        return self


class Trace(DomainModel):
    """Normalized evidence for one Case execution within an Evaluation Run."""

    trace_id: str
    run_id: str
    case_id: str
    spans: tuple[TraceSpan, ...]
    turn_outcomes: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    final_output: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    final_state: FrozenJsonObject = Field(default_factory=FrozenJsonObject)

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, value: str) -> str:
        if not _TRACE_ID_PATTERN.fullmatch(value):
            raise ValueError("trace_id must be exactly 32 lowercase hexadecimal characters")
        return value

    @field_validator("run_id", "case_id")
    @classmethod
    def validate_non_blank(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"Trace {info.field_name}")

    @model_validator(mode="after")
    def validate_spans(self) -> "Trace":
        if any(span.trace_id != self.trace_id for span in self.spans):
            raise ValueError("every TraceSpan must use the owning Trace trace_id")
        span_ids = tuple(span.span_id for span in self.spans)
        if len(set(span_ids)) != len(span_ids):
            raise ValueError("TraceSpan span_ids must be unique within a Trace")
        sequences = tuple(span.sequence for span in self.spans)
        if len(set(sequences)) != len(sequences):
            raise ValueError("TraceSpan sequences must be unique within a Trace")
        return self

    def completion_sequence(self) -> int:
        return max((span.sequence for span in self.spans), default=-1) + 1

    def for_turn(self, turn_id: str) -> "Trace":
        outcome = self.turn_outcomes.get(turn_id)
        if outcome is None:
            if not self.turn_outcomes:
                return self
            raise ValueError(f"trace has no outcome for turn {turn_id}")
        if not isinstance(outcome, FrozenJsonObject):
            raise ValueError(f"trace outcome for turn {turn_id} must be an object")
        spans = tuple(
            span for span in self.spans if span.attributes.get("turn_id") == turn_id
        )
        output = outcome.get("output", FrozenJsonObject())
        state = outcome.get("state", FrozenJsonObject())
        if not isinstance(output, FrozenJsonObject) or not isinstance(state, FrozenJsonObject):
            raise ValueError(f"trace outcome for turn {turn_id} has invalid output or state")
        return self.model_copy(update={
            "spans": spans,
            "final_output": output,
            "final_state": state,
        })
