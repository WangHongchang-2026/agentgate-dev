"""Release-gate configuration and immutable decisions."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import DomainModel, require_non_blank
from .result import Outcome


class ReleaseGateSpec(DomainModel):
    """Versioned threshold applied to one Evaluation Run."""

    id: str = "release-gate"
    version: str = "1"
    minimum_score: float = Field(default=0.95, ge=0, le=1)

    @field_validator("id", "version")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"ReleaseGateSpec {info.field_name}")


ReleaseGateReason: TypeAlias = Literal[
    "threshold_met",
    "score_below_threshold",
    "missing_results",
    "evaluator_error",
    "blocking_failure",
    "review_required",
    "no_applicable_results",
]
ReleaseGateOutcome: TypeAlias = Literal[Outcome.PASS, Outcome.FAIL]


def classify_release_gate(
    *,
    has_missing_results: bool,
    has_evaluator_errors: bool,
    has_blocking_failures: bool,
    has_reviews: bool,
    score: float | None,
    minimum_score: float,
) -> tuple[ReleaseGateOutcome, ReleaseGateReason]:
    """Classify release facts using the fixed fail-closed precedence."""

    if has_missing_results:
        return Outcome.FAIL, "missing_results"
    if has_evaluator_errors:
        return Outcome.FAIL, "evaluator_error"
    if has_blocking_failures:
        return Outcome.FAIL, "blocking_failure"
    if has_reviews:
        return Outcome.FAIL, "review_required"
    if score is None:
        return Outcome.FAIL, "no_applicable_results"
    if score >= minimum_score:
        return Outcome.PASS, "threshold_met"
    return Outcome.FAIL, "score_below_threshold"


class ReleaseGateDecision(DomainModel):
    """Fail-closed release decision derived from Results and the overall Metric."""

    outcome: ReleaseGateOutcome
    missing_results: tuple[tuple[str, str], ...] = ()
    score: float | None = Field(default=None, ge=0, le=1)
    minimum_score: float = Field(ge=0, le=1)
    reason_code: ReleaseGateReason

    @field_validator("missing_results")
    @classmethod
    def validate_missing_results(
        cls, value: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        if any(
            not case_id.strip() or not evaluator_id.strip()
            for case_id, evaluator_id in value
        ):
            raise ValueError("missing_results cannot contain blank identifiers")
        if len(set(value)) != len(value):
            raise ValueError("missing_results must be unique")
        return value

    @model_validator(mode="after")
    def validate_decision(self) -> "ReleaseGateDecision":
        expected_outcome = (
            Outcome.PASS if self.reason_code == "threshold_met" else Outcome.FAIL
        )
        if self.outcome != expected_outcome:
            raise ValueError("release-gate outcome does not match reason_code")
        if self.reason_code == "missing_results" and not self.missing_results:
            raise ValueError("missing_results reason requires missing result references")
        if self.reason_code != "missing_results" and self.missing_results:
            raise ValueError("only missing_results reason may contain missing references")
        if self.reason_code == "threshold_met":
            if self.score is None or self.score < self.minimum_score:
                raise ValueError("threshold_met requires score to meet minimum_score")
        elif self.reason_code == "score_below_threshold":
            if self.score is None or self.score >= self.minimum_score:
                raise ValueError("score_below_threshold requires score below minimum_score")
        elif self.reason_code == "no_applicable_results" and self.score is not None:
            raise ValueError("no_applicable_results requires no score")
        return self
