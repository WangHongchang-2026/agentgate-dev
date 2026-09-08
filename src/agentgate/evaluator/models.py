"""Runtime-only evaluator models; these objects are not persisted."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, TypeAlias

from pydantic import Field, ValidationInfo, field_serializer, field_validator, model_validator

from agentgate.domain import (
    DomainModel, FailureStage, JudgeRecord, MethodRef, Outcome, EvaluationResult, freeze_json,
)
from agentgate.domain.base import require_non_blank, thaw_json


_SPAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


class FailureCandidate(DomainModel):
    stage: FailureStage
    span_id: str | None = None
    at_trace_completion: bool = False

    @field_validator("span_id")
    @classmethod
    def validate_span_id(cls, value: str | None) -> str | None:
        if value is not None and not _SPAN_ID_PATTERN.fullmatch(value):
            raise ValueError("FailureCandidate span_id must be a lowercase OTel Span ID")
        return value

    @model_validator(mode="after")
    def validate_location(self) -> "FailureCandidate":
        if self.span_id is None and not self.at_trace_completion:
            raise ValueError("failure candidate requires span_id or trace-completion marker")
        if self.span_id is not None and self.at_trace_completion:
            raise ValueError("failure candidate cannot use both location forms")
        return self


class CheckDraft(DomainModel):
    name: str
    turn_id: str | None = None
    expectation_id: str | None = None
    outcome: Outcome
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str
    expected: Any = None
    actual: Any = None
    actual_missing: bool = False
    methods: tuple[MethodRef, ...] = ()
    span_ids: tuple[str, ...] = ()
    failure: FailureCandidate | None = None

    @field_validator("name", "reason")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"CheckDraft {info.field_name}")

    @field_validator("turn_id", "expectation_id")
    @classmethod
    def validate_optional_text(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        return require_non_blank(value, f"CheckDraft {info.field_name}") if value else None

    @field_validator("expected", "actual", mode="before")
    @classmethod
    def freeze_values(cls, value: Any) -> Any:
        return freeze_json(value)

    @field_serializer("expected", "actual")
    def serialize_values(self, value: Any) -> Any:
        return thaw_json(value)

    @field_validator("span_ids")
    @classmethod
    def validate_span_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _SPAN_ID_PATTERN.fullmatch(item) for item in value):
            raise ValueError("CheckDraft span_ids must contain lowercase OTel Span IDs")
        if len(set(value)) != len(value):
            raise ValueError("CheckDraft span_ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> "CheckDraft":
        if self.actual_missing and self.actual is not None:
            raise ValueError("missing CheckDraft actual value must be None")
        if self.outcome == Outcome.ERROR:
            raise ValueError("Evaluator execution errors belong on EvaluationResult")
        if self.outcome == Outcome.NOT_APPLICABLE:
            if self.score is not None:
                raise ValueError("not-applicable CheckDraft cannot have a score")
        elif self.score is None:
            raise ValueError("measured CheckDraft requires a score")
        if self.outcome == Outcome.FAIL:
            if self.failure is None:
                raise ValueError("failed CheckDraft requires a failure candidate")
        elif self.failure is not None:
            raise ValueError("only failed CheckDraft may contain a failure candidate")
        return self


class Evaluation(DomainModel):
    checks: tuple[CheckDraft, ...]
    judge_record: JudgeRecord | None = None


class Observation(DomainModel):
    values: tuple[Any, ...]
    span_ids: tuple[str | None, ...] = ()


class OperatorOutcome(DomainModel):
    passed: bool
    reason: str


ResultResolver: TypeAlias = Callable[[str], EvaluationResult]


class EvaluatorError(Exception):
    pass


class EvaluatorKindMismatch(EvaluatorError):
    pass


class UnknownEvaluator(EvaluatorError):
    pass


class UnknownOperator(EvaluatorError):
    pass


class UnsupportedOperator(EvaluatorError):
    pass


class InvalidHybridEvaluator(EvaluatorError):
    pass


class CircularEvaluatorDependency(EvaluatorError):
    pass


class DuplicateEvaluatorId(EvaluatorError):
    pass


class MissingEvaluatorDependency(EvaluatorError):
    pass


class EvaluatorVersionMismatch(EvaluatorError):
    pass
