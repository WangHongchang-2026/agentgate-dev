from agentgate.domain import (
    CheckResult,
    EvaluationResult,
    EvaluatorErrorDetail,
    EvaluatorKind,
    EvaluatorSeverity,
    FailureStage,
    GateSpec,
    Outcome,
)
from agentgate.result.gate import decide_gate


def result(index, outcome=Outcome.PASS, severity=EvaluatorSeverity.STANDARD):
    score = 1.0 if outcome == Outcome.PASS else (
        0.0 if outcome == Outcome.FAIL else None
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
        trace_id="0" * 32,
        case_id=str(index),
        evaluator_id=f"e-{index}",
        evaluator_name="e",
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


def test_one_blocking_failure_cannot_be_averaged_away():
    results = [result(index) for index in range(19)]
    results.append(result(19, Outcome.FAIL, EvaluatorSeverity.BLOCKING))
    gate = decide_gate(results, tuple(item.evaluator_id for item in results), GateSpec())
    assert gate.score == 0.95
    assert gate.outcome == Outcome.FAIL


def test_no_applicable_result_fails_closed():
    item = result(1, Outcome.NOT_APPLICABLE)
    gate = decide_gate([item], (item.evaluator_id,), GateSpec())
    assert gate.outcome == Outcome.FAIL
    assert gate.score is None


def test_evaluator_error_fails_gate_without_agent_score():
    item = result(1, Outcome.ERROR)
    gate = decide_gate([item], (item.evaluator_id,), GateSpec())
    assert gate.outcome == Outcome.FAIL
    assert gate.errors == 1
    assert gate.score is None
