"""Deterministic descriptive breakdowns for one completed Evaluation Run."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from statistics import mean
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentgate.domain import (
    Case,
    CheckResult,
    EvaluationResult,
    EvaluationRun,
    Outcome,
    RunStatus,
    SkillRouteExpectation,
    ToolCallExpectation,
)


AnalyticsDimension: TypeAlias = Literal[
    "evaluator",
    "category",
    "difficulty",
    "tag",
    "routing",
    "tool_use",
    "failure_type",
]
_AggregateItem: TypeAlias = tuple[str, Outcome, float | None]
_Groups: TypeAlias = dict[str, tuple[str, list[_AggregateItem]]]


class AnalyticsBucket(BaseModel):
    """Outcome and score distribution for one analytics key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    case_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    reviewed: int = Field(ge=0)
    not_applicable: int = Field(ge=0)
    errors: int = Field(ge=0)
    applicable: int = Field(ge=0)
    pass_rate: float | None = Field(default=None, ge=0, le=1)
    failure_rate: float | None = Field(default=None, ge=0, le=1)
    average_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_counts(self) -> "AnalyticsBucket":
        if self.observation_count != (
            self.passed
            + self.failed
            + self.reviewed
            + self.not_applicable
            + self.errors
        ):
            raise ValueError("observation_count must equal all outcome counts")
        if self.applicable != self.passed + self.failed + self.reviewed:
            raise ValueError("applicable must equal passed + failed + reviewed")
        if self.case_count > self.observation_count:
            raise ValueError("case_count cannot exceed observation_count")
        expected_pass_rate = self.passed / self.applicable if self.applicable else None
        expected_failure_rate = (
            self.failed / self.applicable if self.applicable else None
        )
        if self.pass_rate != expected_pass_rate:
            raise ValueError("pass_rate does not match outcome counts")
        if self.failure_rate != expected_failure_rate:
            raise ValueError("failure_rate does not match outcome counts")
        if (self.average_score is None) != (self.applicable == 0):
            raise ValueError("average_score must exist exactly for applicable observations")
        return self


class ResultBreakdown(BaseModel):
    """One available or unavailable Result analytics dimension."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: AnalyticsDimension
    available: bool
    buckets: tuple[AnalyticsBucket, ...] = ()

    @model_validator(mode="after")
    def validate_availability(self) -> "ResultBreakdown":
        if self.available != bool(self.buckets):
            raise ValueError("available must match whether breakdown buckets exist")
        keys = tuple(bucket.key for bucket in self.buckets)
        if len(set(keys)) != len(keys):
            raise ValueError("breakdown bucket keys must be unique")
        return self


class ResultAnalytics(BaseModel):
    """All descriptive breakdowns calculated for one completed Run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    by_evaluator: ResultBreakdown
    by_category: ResultBreakdown
    by_difficulty: ResultBreakdown
    by_tag: ResultBreakdown
    by_routing: ResultBreakdown
    by_tool_use: ResultBreakdown
    by_failure_type: ResultBreakdown

    @model_validator(mode="after")
    def validate_dimensions(self) -> "ResultAnalytics":
        expected = {
            "by_evaluator": "evaluator",
            "by_category": "category",
            "by_difficulty": "difficulty",
            "by_tag": "tag",
            "by_routing": "routing",
            "by_tool_use": "tool_use",
            "by_failure_type": "failure_type",
        }
        for field_name, dimension in expected.items():
            if getattr(self, field_name).dimension != dimension:
                raise ValueError(f"{field_name} has the wrong analytics dimension")
        return self


def _add(
    groups: _Groups,
    key: str,
    label: str,
    case_id: str,
    observation: EvaluationResult | CheckResult,
) -> None:
    existing_label, items = groups.setdefault(key, (label, []))
    if existing_label != label:
        raise ValueError(f"analytics key {key!r} has conflicting labels")
    items.append((case_id, observation.outcome, observation.score))


def _bucket(key: str, label: str, items: Sequence[_AggregateItem]) -> AnalyticsBucket:
    passed = sum(outcome is Outcome.PASS for _, outcome, _ in items)
    failed = sum(outcome is Outcome.FAIL for _, outcome, _ in items)
    reviewed = sum(outcome is Outcome.REVIEW for _, outcome, _ in items)
    not_applicable = sum(
        outcome is Outcome.NOT_APPLICABLE for _, outcome, _ in items
    )
    errors = sum(outcome is Outcome.ERROR for _, outcome, _ in items)
    applicable = passed + failed + reviewed
    scores = tuple(score for _, _, score in items if score is not None)
    return AnalyticsBucket(
        key=key,
        label=label,
        case_count=len({case_id for case_id, _, _ in items}),
        observation_count=len(items),
        passed=passed,
        failed=failed,
        reviewed=reviewed,
        not_applicable=not_applicable,
        errors=errors,
        applicable=applicable,
        pass_rate=passed / applicable if applicable else None,
        failure_rate=failed / applicable if applicable else None,
        average_score=mean(scores) if scores else None,
    )


def _breakdown(dimension: AnalyticsDimension, groups: _Groups) -> ResultBreakdown:
    buckets = tuple(
        _bucket(key, label, items)
        for key, (label, items) in sorted(groups.items())
    )
    return ResultBreakdown(
        dimension=dimension,
        available=bool(buckets),
        buckets=buckets,
    )


def _validate_inputs(
    run: EvaluationRun,
    results: tuple[EvaluationResult, ...],
) -> dict[str, Case]:
    if run.status is not RunStatus.COMPLETED:
        raise ValueError("Result analytics requires a completed EvaluationRun")
    result_ids = tuple(result.id for result in results)
    if len(set(result_ids)) != len(result_ids):
        raise ValueError("Result analytics requires unique EvaluationResult ids")
    result_keys = tuple((result.case_id, result.evaluator_id) for result in results)
    if len(set(result_keys)) != len(result_keys):
        raise ValueError("Result analytics requires unique Case and Evaluator pairs")
    if any(result.run_id != run.id for result in results):
        raise ValueError("EvaluationResult belongs to a different Run")
    cases = {case.id: case for case in run.manifest.execution_cases}
    unknown = {result.case_id for result in results}.difference(cases)
    if unknown:
        raise ValueError(
            "EvaluationResults reference unknown Cases: " + ", ".join(sorted(unknown))
        )
    return cases


def calculate_result_analytics(
    run: EvaluationRun,
    results: Sequence[EvaluationResult],
) -> ResultAnalytics:
    """Calculate stable Result and Check distributions without external effects."""

    result_items = tuple(results)
    cases = _validate_inputs(run, result_items)
    evaluator_groups: _Groups = {}
    category_groups: _Groups = {}
    difficulty_groups: _Groups = {}
    tag_groups: _Groups = {}
    failure_groups: _Groups = {}

    for result in result_items:
        case = cases[result.case_id]
        _add(
            evaluator_groups,
            result.evaluator_id,
            result.evaluator_name,
            result.case_id,
            result,
        )
        _add(
            category_groups,
            case.category.value,
            case.category.value,
            result.case_id,
            result,
        )
        _add(
            difficulty_groups,
            case.difficulty.value,
            case.difficulty.value,
            result.case_id,
            result,
        )
        for tag in case.tags:
            _add(tag_groups, tag, tag, result.case_id, result)
        if result.outcome is Outcome.FAIL:
            if result.primary_failure_stage is None:
                raise ValueError("failed Result has no primary failure stage")
            key = result.primary_failure_stage.value
            _add(failure_groups, key, key, result.case_id, result)
        elif result.outcome is Outcome.ERROR:
            if result.error_detail is None:
                raise ValueError("error Result has no error detail")
            key = f"evaluator_error:{result.error_detail.category}"
            _add(failure_groups, key, key, result.case_id, result)

    expectation_index = {
        (case.id, turn.id, expectation.id): expectation
        for case in run.manifest.execution_cases
        for turn in case.turns
        for expectation in turn.expectations
        if isinstance(expectation, (SkillRouteExpectation, ToolCallExpectation))
    }
    routing_groups: _Groups = {}
    tool_groups: _Groups = {}
    for result in result_items:
        for check in result.checks:
            if check.turn_id is None or check.expectation_id is None:
                continue
            expectation = expectation_index.get(
                (result.case_id, check.turn_id, check.expectation_id)
            )
            if isinstance(expectation, SkillRouteExpectation):
                if check.actual_missing:
                    key = "missing"
                elif isinstance(check.actual, str) and check.actual.strip():
                    key = check.actual
                else:
                    key = "ambiguous"
                _add(routing_groups, key, key, result.case_id, check)
            elif isinstance(expectation, ToolCallExpectation):
                _add(
                    tool_groups,
                    expectation.tool,
                    expectation.tool,
                    result.case_id,
                    check,
                )

    return ResultAnalytics(
        run_id=run.id,
        by_evaluator=_breakdown("evaluator", evaluator_groups),
        by_category=_breakdown("category", category_groups),
        by_difficulty=_breakdown("difficulty", difficulty_groups),
        by_tag=_breakdown("tag", tag_groups),
        by_routing=_breakdown("routing", routing_groups),
        by_tool_use=_breakdown("tool_use", tool_groups),
        by_failure_type=_breakdown("failure_type", failure_groups),
    )
