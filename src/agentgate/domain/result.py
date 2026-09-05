"""Persisted evaluation conclusions and their execution provenance."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, ValidationInfo, field_serializer, field_validator, model_validator

from .base import DomainModel, freeze_json, require_non_blank, require_sha256
from .evaluator import EvaluatorKind, EvaluatorSeverity


_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class FailureStage(StrEnum):
    TASK_UNDERSTANDING = "task_understanding"
    PLANNING = "planning"
    CONTEXT_RETRIEVAL = "context_retrieval"
    ROUTING = "routing"
    TOOL_SELECTION = "tool_selection"
    TOOL_ARGUMENTS = "tool_arguments"
    TOOL_EXECUTION = "tool_execution"
    RESULT_INTERPRETATION = "result_interpretation"
    FINAL_STATE = "final_state"
    FINAL_OUTPUT = "final_output"


class MethodRef(DomainModel):
    """Exact implementation used to produce one Check result."""

    implementation_id: str
    implementation_version: str

    @field_validator("implementation_id", "implementation_version")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"MethodRef {info.field_name}")


class JudgeRecord(DomainModel):
    """Audit record for the actual request sent to an LLM Judge."""

    provider_id: str
    requested_model: str
    resolved_model: str | None = None
    request_sha256: str
    raw_response: str
    request_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)

    @field_validator("provider_id", "requested_model")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"JudgeRecord {info.field_name}")

    @field_validator("resolved_model", "request_id")
    @classmethod
    def validate_optional_text(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        return require_non_blank(value, f"JudgeRecord {info.field_name}") if value else None

    @field_validator("request_sha256")
    @classmethod
    def validate_request_hash(cls, value: str) -> str:
        return require_sha256(value, "request_sha256")


class EvaluatorErrorDetail(DomainModel):
    """Sanitized information about an Evaluator execution failure."""

    category: Literal["crash", "timeout", "invalid_output"]
    exception_type: str
    message: str
    retryable: bool = False
    reference: str | None = None

    @field_validator("category", "exception_type", "message")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"EvaluatorErrorDetail {info.field_name}")

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        return require_non_blank(value, "EvaluatorErrorDetail reference") if value else None


class CheckResult(DomainModel):
    """Conclusion for one concrete check within an Evaluator execution."""

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
    span_ids: tuple[str, ...] = ()
    failure_stage: FailureStage | None = None
    failure_sequence: int | None = Field(default=None, ge=0)
    failure_span_id: str | None = None

    @field_validator("id", "name", "reason")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"CheckResult {info.field_name}")

    @field_validator("turn_id", "expectation_id")
    @classmethod
    def validate_optional_text(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        return require_non_blank(value, f"CheckResult {info.field_name}") if value else None

    @field_validator("expected", "actual", mode="before")
    @classmethod
    def freeze_values(cls, value: Any) -> Any:
        return freeze_json(value)

    @field_serializer("expected", "actual")
    def serialize_values(self, value: Any) -> Any:
        from .base import thaw_json

        return thaw_json(value)

    @field_validator("span_ids")
    @classmethod
    def validate_span_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _SPAN_ID_PATTERN.fullmatch(item) for item in value):
            raise ValueError("span_ids must contain lowercase OTel Span IDs")
        if len(set(value)) != len(value):
            raise ValueError("span_ids must be unique")
        return value

    @field_validator("failure_span_id")
    @classmethod
    def validate_failure_span_id(cls, value: str | None) -> str | None:
        if value is not None and not _SPAN_ID_PATTERN.fullmatch(value):
            raise ValueError("failure_span_id must be a lowercase OTel Span ID")
        return value

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> "CheckResult":
        failure_fields = (
            self.failure_stage,
            self.failure_sequence,
            self.failure_span_id,
        )
        if self.outcome == Outcome.ERROR:
            raise ValueError("Evaluator execution errors belong on EvaluationResult")
        if self.outcome == Outcome.FAIL:
            if self.failure_stage is None or self.failure_sequence is None:
                raise ValueError("failed checks require failure_stage and failure_sequence")
            if self.failure_span_id and self.failure_span_id not in self.span_ids:
                raise ValueError("failure_span_id must be included in span_ids")
        elif any(item is not None for item in failure_fields):
            raise ValueError("only failed checks may contain failure location fields")
        if self.outcome == Outcome.NOT_APPLICABLE and self.score is not None:
            raise ValueError("not-applicable checks cannot have a score")
        if self.outcome in (Outcome.PASS, Outcome.FAIL, Outcome.REVIEW) and self.score is None:
            raise ValueError("measured checks require a score")
        return self


class EvaluationResult(DomainModel):
    """One Evaluator's persisted conclusion for one Case execution."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    case_id: str
    trace_id: str
    evaluator_id: str
    evaluator_name: str
    evaluator_version: str
    evaluator_content_sha256: str
    evaluator_kind: EvaluatorKind
    dimension: str
    metric: str
    severity: EvaluatorSeverity
    outcome: Outcome
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str
    checks: tuple[CheckResult, ...] = ()
    judge_record: JudgeRecord | None = None
    error_detail: EvaluatorErrorDetail | None = None
    primary_failure_stage: FailureStage | None = None

    @field_validator(
        "id",
        "run_id",
        "case_id",
        "evaluator_id",
        "evaluator_name",
        "evaluator_version",
        "dimension",
        "metric",
        "reason",
    )
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"EvaluationResult {info.field_name}")

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, value: str) -> str:
        if not _TRACE_ID_PATTERN.fullmatch(value):
            raise ValueError("trace_id must be exactly 32 lowercase hexadecimal characters")
        return value

    @field_validator("evaluator_content_sha256")
    @classmethod
    def validate_evaluator_hash(cls, value: str) -> str:
        return require_sha256(value, "evaluator_content_sha256")

    @model_validator(mode="after")
    def validate_result(self) -> "EvaluationResult":
        check_ids = tuple(item.id for item in self.checks)
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("CheckResult ids must be unique within an EvaluationResult")

        if self.outcome in (Outcome.NOT_APPLICABLE, Outcome.ERROR):
            if self.score is not None:
                raise ValueError("not-applicable/error results cannot have a score")
        elif self.score is None:
            raise ValueError("measured results require a score")

        failed = tuple(item for item in self.checks if item.outcome == Outcome.FAIL)
        reviewed = tuple(item for item in self.checks if item.outcome == Outcome.REVIEW)
        passed = tuple(item for item in self.checks if item.outcome == Outcome.PASS)

        if self.outcome == Outcome.FAIL:
            if not failed:
                raise ValueError("failed results require at least one failed CheckResult")
            earliest = min(failed, key=lambda item: item.failure_sequence or 0)
            if self.primary_failure_stage != earliest.failure_stage:
                raise ValueError("primary_failure_stage must match the earliest failed check")
        elif self.primary_failure_stage is not None:
            raise ValueError("only failed results may have primary_failure_stage")

        if self.outcome == Outcome.PASS and (not passed or failed or reviewed):
            raise ValueError("passed results require passed checks and no failed/review checks")
        if self.outcome == Outcome.REVIEW and (not reviewed or failed):
            raise ValueError("review results require review checks and no failed checks")
        if self.outcome == Outcome.NOT_APPLICABLE and any(
            item.outcome != Outcome.NOT_APPLICABLE for item in self.checks
        ):
            raise ValueError("not-applicable results may contain only not-applicable checks")

        if self.outcome == Outcome.ERROR:
            if self.error_detail is None:
                raise ValueError("error results require error_detail")
        elif self.error_detail is not None:
            raise ValueError("only error results may carry error_detail")

        if self.evaluator_kind != EvaluatorKind.LLM_JUDGE and self.judge_record is not None:
            raise ValueError("only LLM Judge results may carry judge_record")
        if (
            self.evaluator_kind == EvaluatorKind.LLM_JUDGE
            and self.outcome in (Outcome.PASS, Outcome.FAIL, Outcome.REVIEW)
            and self.judge_record is None
        ):
            raise ValueError("measured LLM Judge results require judge_record")
        return self
