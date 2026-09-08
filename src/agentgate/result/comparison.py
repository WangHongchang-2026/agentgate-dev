"""Deterministic comparison of two compatible evaluation reports."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field, ValidationInfo, field_validator, model_validator

from agentgate.domain import (
    DomainModel,
    EvaluationReport,
    MetricLevel,
    MetricSummary,
    Outcome,
    ReleaseGateDecision,
)
from agentgate.domain.base import require_non_blank


ComparisonChange: TypeAlias = Literal[
    "unchanged",
    "improvement",
    "regression",
    "changed",
]


class MetricDelta(DomainModel):
    """Before/after values for one compatible metric summary."""

    level: MetricLevel
    key: str
    baseline: MetricSummary
    candidate: MetricSummary
    score_delta: float | None = None

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return require_non_blank(value, "MetricDelta key")

    @model_validator(mode="after")
    def validate_delta(self) -> "MetricDelta":
        identity = (self.level, self.key)
        if identity != (self.baseline.level, self.baseline.key):
            raise ValueError("MetricDelta baseline identity does not match")
        if identity != (self.candidate.level, self.candidate.key):
            raise ValueError("MetricDelta candidate identity does not match")
        expected = _score_delta(self.baseline.score, self.candidate.score)
        if self.score_delta != expected:
            raise ValueError("MetricDelta score_delta does not match its summaries")
        return self


class CaseDelta(DomainModel):
    """Outcome and score change for one Case and primary Evaluator."""

    case_id: str
    evaluator_id: str
    baseline_outcome: Outcome | None = None
    candidate_outcome: Outcome | None = None
    baseline_score: float | None = Field(default=None, ge=0, le=1)
    candidate_score: float | None = Field(default=None, ge=0, le=1)
    score_delta: float | None = None
    change: ComparisonChange

    @field_validator("case_id", "evaluator_id")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"CaseDelta {info.field_name}")

    @model_validator(mode="after")
    def validate_delta(self) -> "CaseDelta":
        expected_delta = _score_delta(self.baseline_score, self.candidate_score)
        if self.score_delta != expected_delta:
            raise ValueError("CaseDelta score_delta does not match its scores")
        expected_change = _classify_change(
            self.baseline_outcome,
            self.candidate_outcome,
            expected_delta,
        )
        if self.change != expected_change:
            raise ValueError("CaseDelta change does not match its outcomes and scores")
        return self


class EvaluationComparison(DomainModel):
    """Complete deterministic difference between two evaluation reports."""

    baseline_run_id: str
    candidate_run_id: str
    baseline_target_version: str
    candidate_target_version: str
    baseline_gate: ReleaseGateDecision
    candidate_gate: ReleaseGateDecision
    overall_score_delta: float | None = None
    metric_deltas: tuple[MetricDelta, ...]
    case_deltas: tuple[CaseDelta, ...]

    @field_validator(
        "baseline_run_id",
        "candidate_run_id",
        "baseline_target_version",
        "candidate_target_version",
    )
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"EvaluationComparison {info.field_name}")

    @model_validator(mode="after")
    def validate_comparison(self) -> "EvaluationComparison":
        metric_keys = tuple((item.level, item.key) for item in self.metric_deltas)
        if len(set(metric_keys)) != len(metric_keys):
            raise ValueError("EvaluationComparison metric identities must be unique")
        overall = tuple(
            item
            for item in self.metric_deltas
            if item.level == "overall" and item.key == "overall"
        )
        if len(overall) != 1 or self.overall_score_delta != overall[0].score_delta:
            raise ValueError("EvaluationComparison requires one matching overall delta")
        case_keys = tuple(
            (item.case_id, item.evaluator_id) for item in self.case_deltas
        )
        if len(set(case_keys)) != len(case_keys):
            raise ValueError("EvaluationComparison Case identities must be unique")
        return self


def _score_delta(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None:
        return None
    return candidate - baseline


def _primary_evaluator_signature(
    report: EvaluationReport,
) -> tuple[tuple[str, str, str], ...]:
    manifest = report.run.manifest
    specs = {item.id: item for item in manifest.evaluator_specs}
    return tuple(
        (evaluator_id, specs[evaluator_id].version, specs[evaluator_id].content_sha256)
        for evaluator_id in manifest.primary_evaluator_ids
    )


def _validate_compatible(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> None:
    baseline_manifest = baseline.run.manifest
    candidate_manifest = candidate.run.manifest

    baseline_ref = baseline_manifest.target.ref
    candidate_ref = candidate_manifest.target.ref
    baseline_target = (
        baseline_ref.source_id,
        baseline_ref.target_type,
        baseline_ref.external_target_id,
    )
    candidate_target = (
        candidate_ref.source_id,
        candidate_ref.target_type,
        candidate_ref.external_target_id,
    )
    if baseline_target != candidate_target:
        raise ValueError("reports reference different Agent or Skill targets")

    baseline_dataset = baseline_manifest.dataset
    candidate_dataset = candidate_manifest.dataset
    if baseline_dataset.dataset_id != candidate_dataset.dataset_id:
        raise ValueError("reports reference different Datasets")
    if baseline_dataset.content_sha256 != candidate_dataset.content_sha256:
        raise ValueError("reports use different Dataset content")
    baseline_cases = tuple(item.id for item in baseline_dataset.cases)
    candidate_cases = tuple(item.id for item in candidate_dataset.cases)
    if baseline_cases != candidate_cases:
        raise ValueError("reports use different ordered Case identities")

    if _primary_evaluator_signature(baseline) != _primary_evaluator_signature(
        candidate
    ):
        raise ValueError("reports use different primary Evaluators")
    if baseline_manifest.metric_plan != candidate_manifest.metric_plan:
        raise ValueError("reports use different Metric plans")
    if baseline_manifest.gate_spec != candidate_manifest.gate_spec:
        raise ValueError("reports use different release-gate specifications")


def _compare_metrics(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> tuple[MetricDelta, ...]:
    candidate_metrics = {(item.level, item.key): item for item in candidate.metrics}
    baseline_keys = {(item.level, item.key) for item in baseline.metrics}
    if baseline_keys != set(candidate_metrics):
        raise ValueError("reports contain different metric summaries")
    return tuple(
        MetricDelta(
            level=item.level,
            key=item.key,
            baseline=item,
            candidate=candidate_metrics[(item.level, item.key)],
            score_delta=_score_delta(
                item.score,
                candidate_metrics[(item.level, item.key)].score,
            ),
        )
        for item in baseline.metrics
    )


def _classify_change(
    baseline_outcome: Outcome | None,
    candidate_outcome: Outcome | None,
    score_delta: float | None,
) -> ComparisonChange:
    if baseline_outcome == candidate_outcome and score_delta in (None, 0):
        return "unchanged"
    if baseline_outcome == Outcome.PASS and candidate_outcome != Outcome.PASS:
        return "regression"
    if baseline_outcome != Outcome.PASS and candidate_outcome == Outcome.PASS:
        return "improvement"
    if score_delta is not None:
        if score_delta > 0:
            return "improvement"
        if score_delta < 0:
            return "regression"
    return "changed"


def _compare_cases(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> tuple[CaseDelta, ...]:
    baseline_results = {
        (item.case_id, item.evaluator_id): item for item in baseline.results
    }
    candidate_results = {
        (item.case_id, item.evaluator_id): item for item in candidate.results
    }
    manifest = baseline.run.manifest
    deltas: list[CaseDelta] = []
    for case in manifest.dataset.cases:
        for evaluator_id in manifest.primary_evaluator_ids:
            key = (case.id, evaluator_id)
            before = baseline_results.get(key)
            after = candidate_results.get(key)
            score_delta = _score_delta(
                before.score if before else None,
                after.score if after else None,
            )
            deltas.append(
                CaseDelta(
                    case_id=case.id,
                    evaluator_id=evaluator_id,
                    baseline_outcome=before.outcome if before else None,
                    candidate_outcome=after.outcome if after else None,
                    baseline_score=before.score if before else None,
                    candidate_score=after.score if after else None,
                    score_delta=score_delta,
                    change=_classify_change(
                        before.outcome if before else None,
                        after.outcome if after else None,
                        score_delta,
                    ),
                )
            )
    return tuple(deltas)


def compare_reports(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> EvaluationComparison:
    """Compare two completed reports produced from compatible evaluation inputs."""

    _validate_compatible(baseline, candidate)
    metric_deltas = _compare_metrics(baseline, candidate)
    overall = next(
        item for item in metric_deltas if item.level == "overall" and item.key == "overall"
    )
    return EvaluationComparison(
        baseline_run_id=baseline.run.id,
        candidate_run_id=candidate.run.id,
        baseline_target_version=(
            baseline.run.manifest.target.ref.external_version_id
        ),
        candidate_target_version=(
            candidate.run.manifest.target.ref.external_version_id
        ),
        baseline_gate=baseline.release_gate,
        candidate_gate=candidate.release_gate,
        overall_score_delta=overall.score_delta,
        metric_deltas=metric_deltas,
        case_deltas=_compare_cases(baseline, candidate),
    )


__all__ = [
    "CaseDelta",
    "ComparisonChange",
    "EvaluationComparison",
    "MetricDelta",
    "compare_reports",
]
