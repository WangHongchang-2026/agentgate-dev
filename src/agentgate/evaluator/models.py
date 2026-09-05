"""Runtime-only evaluator models; these objects are not persisted."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import Field, field_serializer, field_validator, model_validator

from agentgate.domain import (
    DomainModel, FailureStage, JudgeRecord, MethodRef, Outcome, EvaluationResult, freeze_json,
)


class FailureCandidate(DomainModel):
    stage: FailureStage
    span_id: str | None = None
    at_trace_completion: bool = False

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

    @field_validator("expected", "actual", mode="before")
    @classmethod
    def freeze_values(cls, value: Any) -> Any:
        return freeze_json(value)

    @field_serializer("expected", "actual")
    def serialize_values(self, value: Any) -> Any:
        from agentgate.domain.base import thaw_json
        return thaw_json(value)


class Evaluation(DomainModel):
    checks: tuple[CheckDraft, ...]
    judge_record: JudgeRecord | None = None


class Observation(DomainModel):
    values: tuple[Any, ...]
    span_ids: tuple[str | None, ...] = ()


class OperatorOutcome(DomainModel):
    passed: bool
    reason: str


ResultResolver = Callable[[str], EvaluationResult]


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
