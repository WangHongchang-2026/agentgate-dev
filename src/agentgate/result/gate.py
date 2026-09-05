"""Apply a ReleaseGateSpec to primary Evaluation Results."""

from __future__ import annotations

from collections.abc import Sequence

from agentgate.domain import (
    EvaluationResult,
    EvaluatorSeverity,
    MetricSummary,
    Outcome,
    ReleaseGateDecision,
    ReleaseGateSpec,
    classify_release_gate,
)


def decide_release_gate(
    results: Sequence[EvaluationResult],
    metrics: Sequence[MetricSummary],
    expected_case_ids: tuple[str, ...],
    primary_evaluator_ids: tuple[str, ...],
    spec: ReleaseGateSpec,
) -> ReleaseGateDecision:
    """Return a fail-closed decision without recalculating metric scores."""

    primary_ids = set(primary_evaluator_ids)
    primary = tuple(item for item in results if item.evaluator_id in primary_ids)
    result_keys = tuple((item.case_id, item.evaluator_id) for item in primary)
    if len(set(result_keys)) != len(result_keys):
        raise ValueError("primary Evaluation Results must be unique by Case and Evaluator")

    actual_keys = set(result_keys)
    missing_results = tuple(
        (case_id, evaluator_id)
        for case_id in expected_case_ids
        for evaluator_id in primary_evaluator_ids
        if (case_id, evaluator_id) not in actual_keys
    )
    overall_metrics = tuple(item for item in metrics if item.level == "overall")
    if len(overall_metrics) != 1:
        raise ValueError("release-gate evaluation requires exactly one overall MetricSummary")
    score = overall_metrics[0].score
    outcome, reason_code = classify_release_gate(
        has_missing_results=bool(missing_results),
        has_evaluator_errors=any(
            item.outcome == Outcome.ERROR for item in primary
        ),
        has_blocking_failures=any(
            item.severity == EvaluatorSeverity.BLOCKING
            and item.outcome == Outcome.FAIL
            for item in primary
        ),
        has_reviews=any(item.outcome == Outcome.REVIEW for item in primary),
        score=score,
        minimum_score=spec.minimum_score,
    )

    return ReleaseGateDecision(
        outcome=outcome,
        score=score,
        minimum_score=spec.minimum_score,
        reason_code=reason_code,
        missing_results=missing_results,
    )
