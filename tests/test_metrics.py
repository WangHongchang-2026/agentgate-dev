import pytest

from agentgate.domain import (
    CheckResult, EvaluationResult, FailureStage, EvaluatorKind, MetricPlan,
    Outcome, EvaluatorSeverity,
)
from agentgate.result.calc_metrics import calculate_metrics


def result(case, evaluator, metric, dimension, score, kind=EvaluatorKind.RULE):
    outcome = Outcome.PASS if score == 1 else Outcome.FAIL
    return EvaluationResult(
        run_id="run",
        trace_id="0" * 32,
        case_id=case,
        evaluator_id=evaluator,
        evaluator_name=evaluator,
        evaluator_version="1",
        evaluator_content_sha256="a" * 64,
        evaluator_kind=kind,
        dimension=dimension,
        metric=metric,
        severity=EvaluatorSeverity.STANDARD,
        outcome=outcome,
        score=score,
        reason="test",
        checks=(CheckResult(
            name="test", outcome=outcome, score=score, reason="test",
            failure_stage=FailureStage.FINAL_STATE if outcome == Outcome.FAIL else None,
            failure_sequence=0 if outcome == Outcome.FAIL else None,
        ),),
        primary_failure_stage=FailureStage.FINAL_STATE if outcome == Outcome.FAIL else None,
    )


def test_metric_dimension_kind_and_overall_paths_do_not_double_count():
    results = [
        result("a", "one", "m1", "tool_use", 1.0),
        result("a", "two", "m2", "tool_use", 0.0),
        result("a", "three", "m3", "state", 1.0),
    ]
    summaries = calculate_metrics(results, ("one", "two", "three"), MetricPlan())
    by_key = {(item.level, item.key): item for item in summaries}
    assert by_key[("dimension", "tool_use")].score == 0.5
    assert by_key[("dimension", "state")].score == 1.0
    assert by_key[("kind", "rule")].score == pytest.approx(2 / 3)
    assert by_key[("overall", "overall")].score == 0.75
