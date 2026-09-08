"""Complete, internally consistent evaluation report."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field, model_validator

from .base import DomainModel
from .evaluator import EvaluatorSeverity
from .gate import ReleaseGateDecision, classify_release_gate
from .metric import MetricSummary
from .result import EvaluationResult, Outcome
from .run import EvaluationRun, RunManifest, RunStatus


def _validate_results(
    run: EvaluationRun,
    results: Sequence[EvaluationResult],
) -> set[tuple[str, str]]:
    case_ids = {item.id for item in run.manifest.execution_cases}
    evaluator_specs = {item.id: item for item in run.manifest.evaluator_specs}
    result_keys: list[tuple[str, str]] = []
    for result in results:
        if result.run_id != run.id:
            raise ValueError("EvaluationResult belongs to a different Run")
        if result.case_id not in case_ids:
            raise ValueError("EvaluationResult references an unknown Case")
        spec = evaluator_specs.get(result.evaluator_id)
        if spec is None:
            raise ValueError("EvaluationResult references an unknown Evaluator")
        expected_evaluator = (
            spec.name,
            spec.version,
            spec.content_sha256,
            spec.kind,
            spec.dimension,
            spec.metric,
            spec.severity,
        )
        actual_evaluator = (
            result.evaluator_name,
            result.evaluator_version,
            result.evaluator_content_sha256,
            result.evaluator_kind,
            result.dimension,
            result.metric,
            result.severity,
        )
        if actual_evaluator != expected_evaluator:
            raise ValueError("EvaluationResult does not match its RunManifest Evaluator")
        result_keys.append((result.case_id, result.evaluator_id))
    if len(set(result_keys)) != len(result_keys):
        raise ValueError("Evaluation Results must be unique by Case and Evaluator")
    return set(result_keys)


def _overall_metric(metrics: Sequence[MetricSummary]) -> MetricSummary:
    metric_keys = tuple((item.level, item.key) for item in metrics)
    if len(set(metric_keys)) != len(metric_keys):
        raise ValueError("Metric summaries must be unique by level and key")
    overall = tuple(item for item in metrics if item.level == "overall")
    if len(overall) != 1 or overall[0].key != "overall":
        raise ValueError("EvaluationReport requires one overall MetricSummary")
    return overall[0]


def _validate_overall_counts(
    overall: MetricSummary,
    primary: Sequence[EvaluationResult],
) -> None:
    expected = (
        sum(item.outcome == Outcome.PASS for item in primary),
        sum(item.outcome == Outcome.FAIL for item in primary),
        sum(item.outcome == Outcome.REVIEW for item in primary),
        sum(item.outcome == Outcome.NOT_APPLICABLE for item in primary),
        sum(item.outcome == Outcome.ERROR for item in primary),
        sum(
            item.outcome in (Outcome.PASS, Outcome.FAIL, Outcome.REVIEW)
            for item in primary
        ),
        len(primary),
    )
    actual = (
        overall.passed,
        overall.failed,
        overall.reviewed,
        overall.not_applicable,
        overall.errors,
        overall.applicable,
        overall.total,
    )
    if actual != expected:
        raise ValueError("overall Metric counts do not match primary Evaluation Results")


def _missing_results(
    manifest: RunManifest,
    result_keys: set[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (case.id, evaluator_id)
        for case in manifest.execution_cases
        for evaluator_id in manifest.primary_evaluator_ids
        if (case.id, evaluator_id) not in result_keys
    )


def _validate_release_gate(
    manifest: RunManifest,
    primary: Sequence[EvaluationResult],
    overall: MetricSummary,
    missing_results: tuple[tuple[str, str], ...],
    decision: ReleaseGateDecision,
) -> None:
    if decision.score != overall.score:
        raise ValueError("release-gate score must equal the overall Metric score")
    if decision.minimum_score != manifest.gate_spec.minimum_score:
        raise ValueError("release-gate minimum_score must match the RunManifest")
    if decision.missing_results != missing_results:
        raise ValueError("release-gate missing_results do not match the RunManifest")
    expected = classify_release_gate(
        has_missing_results=bool(missing_results),
        has_evaluator_errors=any(item.outcome == Outcome.ERROR for item in primary),
        has_blocking_failures=any(
            item.severity == EvaluatorSeverity.BLOCKING
            and item.outcome == Outcome.FAIL
            for item in primary
        ),
        has_reviews=any(item.outcome == Outcome.REVIEW for item in primary),
        score=overall.score,
        minimum_score=manifest.gate_spec.minimum_score,
    )
    if (decision.outcome, decision.reason_code) != expected:
        raise ValueError("release-gate decision does not match Evaluation Results")


class EvaluationReport(DomainModel):
    """Final read model for one completed Evaluation Run."""

    run: EvaluationRun
    results: tuple[EvaluationResult, ...] = ()
    metrics: tuple[MetricSummary, ...] = Field(min_length=1)
    release_gate: ReleaseGateDecision

    @model_validator(mode="after")
    def validate_report(self) -> "EvaluationReport":
        if self.run.status != RunStatus.COMPLETED:
            raise ValueError("EvaluationReport requires a completed EvaluationRun")
        result_keys = _validate_results(self.run, self.results)
        overall = _overall_metric(self.metrics)
        primary_ids = set(self.run.manifest.primary_evaluator_ids)
        primary = tuple(
            item for item in self.results if item.evaluator_id in primary_ids
        )
        _validate_overall_counts(overall, primary)
        missing = _missing_results(self.run.manifest, result_keys)
        _validate_release_gate(
            self.run.manifest,
            primary,
            overall,
            missing,
            self.release_gate,
        )
        return self
