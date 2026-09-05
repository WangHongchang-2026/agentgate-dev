import pytest
from pydantic import ValidationError

from agentgate.domain import (
    CheckResult,
    EvaluationResult,
    EvaluatorErrorDetail,
    EvaluatorKind,
    EvaluatorSeverity,
    FailureStage,
    MetricPlan,
    Outcome,
    ReleaseGateDecision,
    ReleaseGateSpec,
)
from agentgate.result.metrics import calculate_metrics
from agentgate.result.gate import decide_release_gate


def result(index, outcome=Outcome.PASS, severity=EvaluatorSeverity.STANDARD):
    score = (
        1.0 if outcome == Outcome.PASS
        else 0.0 if outcome == Outcome.FAIL
        else 0.5 if outcome == Outcome.REVIEW
        else None
    )
    checks = () if outcome == Outcome.ERROR else (CheckResult(
        name="test",
        outcome=outcome,
        score=score,
        reason="test",
        failure_stage=FailureStage.FINAL_STATE if outcome == Outcome.FAIL else None,
        failure_sequence=0 if outcome == Outcome.FAIL else None,
    ),)
    return EvaluationResult(
        run_id="run",
        trace_id=f"{index + 1:032x}",
        case_id=f"case-{index}",
        evaluator_id="evaluator",
        evaluator_name="Evaluator",
        evaluator_version="1",
        evaluator_content_sha256="a" * 64,
        evaluator_kind=EvaluatorKind.RULE,
        dimension="safety",
        metric="policy",
        severity=severity,
        outcome=outcome,
        score=score,
        reason="test",
        checks=checks,
        error_detail=EvaluatorErrorDetail(
            category="crash",
            exception_type="RuntimeError",
            message="failed",
        ) if outcome == Outcome.ERROR else None,
        primary_failure_stage=(
            FailureStage.FINAL_STATE if outcome == Outcome.FAIL else None
        ),
    )


def decide(results, expected_case_ids=None, spec=None):
    evaluator_ids = ("evaluator",)
    metrics = calculate_metrics(list(results), evaluator_ids, MetricPlan())
    return decide_release_gate(
        results,
        metrics,
        expected_case_ids or tuple(item.case_id for item in results),
        evaluator_ids,
        spec or ReleaseGateSpec(),
    )


def test_one_blocking_failure_cannot_be_averaged_away():
    results = [result(index) for index in range(19)]
    results.append(result(19, Outcome.FAIL, EvaluatorSeverity.BLOCKING))
    gate = decide(results)
    assert gate.score == 0.95
    assert gate.outcome == Outcome.FAIL
    assert gate.reason_code == "blocking_failure"


def test_standard_failure_can_pass_when_overall_score_meets_threshold():
    results = [result(index) for index in range(19)]
    results.append(result(19, Outcome.FAIL))
    gate = decide(results)
    assert gate.score == 0.95
    assert gate.outcome == Outcome.PASS
    assert gate.reason_code == "threshold_met"


def test_missing_result_fails_closed():
    gate = decide([result(0)], expected_case_ids=("case-0", "case-1"))
    assert gate.outcome == Outcome.FAIL
    assert gate.reason_code == "missing_results"
    assert gate.missing_results == (("case-1", "evaluator"),)


def test_missing_matrix_covers_every_primary_evaluator():
    results = [result(0)]
    evaluator_ids = ("evaluator", "other")
    metrics = calculate_metrics(results, evaluator_ids, MetricPlan())
    gate = decide_release_gate(
        results,
        metrics,
        ("case-0", "case-1"),
        evaluator_ids,
        ReleaseGateSpec(),
    )
    assert gate.missing_results == (
        ("case-0", "other"),
        ("case-1", "evaluator"),
        ("case-1", "other"),
    )


def test_no_applicable_result_fails_closed():
    gate = decide([result(1, Outcome.NOT_APPLICABLE)])
    assert gate.outcome == Outcome.FAIL
    assert gate.reason_code == "no_applicable_results"
    assert gate.score is None


def test_not_applicable_result_does_not_block_an_applicable_pass():
    gate = decide([result(0), result(1, Outcome.NOT_APPLICABLE)])
    assert gate.outcome == Outcome.PASS
    assert gate.reason_code == "threshold_met"


def test_evaluator_error_fails_gate_without_agent_score():
    gate = decide([result(1, Outcome.ERROR)])
    assert gate.outcome == Outcome.FAIL
    assert gate.reason_code == "evaluator_error"
    assert gate.score is None


def test_review_and_low_score_fail_with_specific_reasons():
    review_gate = decide([result(0, Outcome.REVIEW)])
    assert review_gate.reason_code == "review_required"

    low_score_gate = decide([result(0), result(1, Outcome.FAIL)])
    assert low_score_gate.score == 0.5
    assert low_score_gate.reason_code == "score_below_threshold"


def test_release_gate_decision_rejects_incoherent_values():
    with pytest.raises(ValidationError, match="threshold_met requires"):
        ReleaseGateDecision(
            outcome=Outcome.PASS,
            score=0.5,
            minimum_score=0.9,
            reason_code="threshold_met",
        )
    with pytest.raises(ValidationError, match="outcome does not match"):
        ReleaseGateDecision(
            outcome=Outcome.FAIL,
            score=1.0,
            minimum_score=0.9,
            reason_code="threshold_met",
        )
    with pytest.raises(ValidationError, match="requires missing result"):
        ReleaseGateDecision(
            outcome=Outcome.FAIL,
            score=1.0,
            minimum_score=0.9,
            reason_code="missing_results",
        )
