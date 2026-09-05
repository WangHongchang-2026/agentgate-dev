"""Detailed evaluation results."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, field_serializer, field_validator, model_validator

from .base import DomainModel, freeze_json
from .evaluator import Dimension, JudgeEvidence, Kind, MethodRef, Severity


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class FailureStage(StrEnum):
    ROUTING = "routing"
    TOOL_SELECTION = "tool_selection"
    TOOL_ARGUMENTS = "tool_arguments"
    TOOL_EXECUTION = "tool_execution"
    FINAL_STATE = "final_state"
    FINAL_OUTPUT = "final_output"


class FailureObservation(DomainModel):
    stage: FailureStage
    observed_at_sequence: int = Field(ge=0)
    span_id: str | None = None


class Evidence(DomainModel):
    trace_id: str
    span_ids: tuple[str, ...] = ()
    description: str
    document_refs: tuple[str, ...] = ()


class EvaluationErrorEvidence(DomainModel):
    category: Literal["crash", "timeout", "invalid_output"]
    exception_type: str
    message: str
    retryable: bool = False
    reference: str | None = None


class CheckResult(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
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
    evidence: tuple[Evidence, ...] = ()
    failure_observation: FailureObservation | None = None

    @field_validator("expected", "actual", mode="before")
    @classmethod
    def freeze_values(cls, value: Any) -> Any:
        return freeze_json(value)

    @field_serializer("expected", "actual")
    def serialize_values(self, value: Any) -> Any:
        from .base import thaw_json
        return thaw_json(value)

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> "CheckResult":
        if self.outcome == Outcome.FAIL and self.failure_observation is None:
            raise ValueError("failed checks require failure_observation")
        if self.outcome != Outcome.FAIL and self.failure_observation is not None:
            raise ValueError("only failed checks may have failure_observation")
        if self.outcome in (Outcome.NOT_APPLICABLE, Outcome.ERROR) and self.score is not None:
            raise ValueError("not-applicable/error checks cannot have a score")
        if self.outcome in (Outcome.PASS, Outcome.FAIL, Outcome.REVIEW) and self.score is None:
            raise ValueError("measured checks require a score")
        return self


class Result(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    case_id: str
    evaluator_id: str
    evaluator_name: str
    evaluator_version: str
    evaluator_kind: Kind
    dimension: Dimension
    metric: str
    severity: Severity
    outcome: Outcome
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str
    checks: tuple[CheckResult, ...] = ()
    methods: tuple[MethodRef, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    judge_evidence: JudgeEvidence | None = None
    error_evidence: EvaluationErrorEvidence | None = None
    primary_failure_step: FailureStage | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "Result":
        if self.outcome in (Outcome.NOT_APPLICABLE, Outcome.ERROR) and self.score is not None:
            raise ValueError("not-applicable/error results cannot have a score")
        if self.outcome in (Outcome.PASS, Outcome.FAIL, Outcome.REVIEW) and self.score is None:
            raise ValueError("measured results require a score")
        if self.outcome == Outcome.FAIL:
            if self.primary_failure_step is None:
                raise ValueError("failed results require primary_failure_step")
            if not any(item.outcome == Outcome.FAIL for item in self.checks):
                raise ValueError("failed results require at least one failed CheckResult")
        elif self.primary_failure_step is not None:
            raise ValueError("only failed results may have primary_failure_step")
        if self.outcome == Outcome.ERROR:
            if self.error_evidence is None or self.primary_failure_step is not None:
                raise ValueError("error results require error evidence and no failure stage")
        elif self.error_evidence is not None:
            raise ValueError("only error results may carry error evidence")
        return self
