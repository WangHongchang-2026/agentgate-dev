import pytest

from pydantic import ValidationError

from agentgate.domain import (
    CheckResult, EvaluationResult, FailureStage, EvaluatorKind, MetricPlan, MetricSummary,
    Outcome, EvaluatorSeverity,
)
from agentgate.result.metrics import calculate_metrics


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


def test_metric_summary_enforces_count_and_score_invariants():
    with pytest.raises(ValidationError, match="total must equal"):
        MetricSummary(
            key="routing", level="metric", score=1.0, passed=1, applicable=1
        )
    with pytest.raises(ValidationError, match="score must exist"):
        MetricSummary(key="routing", level="metric", total=0, score=1.0)
    with pytest.raises(ValidationError, match="overall level and key"):
        MetricSummary(key="overall", level="metric")


def test_metric_contract_keeps_identity_separate_from_display_text():
    assert MetricPlan().model_dump() == {"id": "p1-equal-mean", "version": "1"}
    summary = MetricSummary(
        key="customer_metric",
        level="metric",
        score=1.0,
        passed=1,
        applicable=1,
        total=1,
    )
    assert summary.model_dump()["key"] == "customer_metric"
    assert "label" not in summary.model_dump()


def test_metric_plan_version_must_have_an_implementation():
    with pytest.raises(ValueError, match="unsupported MetricPlan"):
        calculate_metrics([], (), MetricPlan(version="2"))


def test_one_metric_key_cannot_belong_to_multiple_dimensions():
    results = [
        result("a", "one", "shared", "routing", 1.0),
        result("b", "two", "shared", "tool_use", 1.0),
    ]
    with pytest.raises(ValueError, match="belongs to multiple dimensions"):
        calculate_metrics(results, ("one", "two"), MetricPlan())
