import pytest

from agentgate.domain import (
    CheckResult,
    EvaluationResult,
    EvaluatorKind,
    EvaluatorSeverity,
    FailureStage,
    Outcome,
)
from agentgate.optimizer.clustering import cluster_failed_results


TRACE_ID = "a" * 32
EVALUATOR_HASH = "b" * 64
SPAN_ONE = "1" * 16
SPAN_TWO = "2" * 16


def failed_result(
    result_id: str,
    *,
    run_id: str = "run-1",
    case_id: str = "case-1",
    evaluator_id: str = "routing",
    dimension: str = "routing",
    metric: str = "skill_route",
    severity: EvaluatorSeverity = EvaluatorSeverity.STANDARD,
    failure_stage: FailureStage = FailureStage.ROUTING,
    span_ids: tuple[str, ...] = (SPAN_ONE,),
) -> EvaluationResult:
    check = CheckResult(
        id=f"check-{result_id}",
        name="failed check",
        outcome=Outcome.FAIL,
        score=0,
        reason="route did not match",
        span_ids=span_ids,
        failure_stage=failure_stage,
        failure_sequence=1,
        failure_span_id=span_ids[0] if span_ids else None,
    )
    return EvaluationResult(
        id=result_id,
        run_id=run_id,
        case_id=case_id,
        trace_id=TRACE_ID,
        evaluator_id=evaluator_id,
        evaluator_name=evaluator_id.title(),
        evaluator_version="1",
        evaluator_content_sha256=EVALUATOR_HASH,
        evaluator_kind=EvaluatorKind.RULE,
        dimension=dimension,
        metric=metric,
        severity=severity,
        outcome=Outcome.FAIL,
        score=0,
        reason=f"{result_id} failed",
        checks=(check,),
        primary_failure_stage=failure_stage,
    )


def passing_result(result_id: str) -> EvaluationResult:
    check = CheckResult(
        id=f"check-{result_id}",
        name="passing check",
        outcome=Outcome.PASS,
        score=1,
        reason="passed",
    )
    return EvaluationResult(
        id=result_id,
        run_id="run-1",
        case_id="case-1",
        trace_id=TRACE_ID,
        evaluator_id="routing",
        evaluator_name="Routing",
        evaluator_version="1",
        evaluator_content_sha256=EVALUATOR_HASH,
        evaluator_kind=EvaluatorKind.RULE,
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        outcome=Outcome.PASS,
        score=1,
        reason="passed",
        checks=(check,),
    )


def test_groups_results_and_calculates_result_and_case_distribution() -> None:
    results = (
        failed_result("result-3", case_id="case-2"),
        failed_result("result-1"),
        failed_result("result-2"),
        failed_result(
            "result-4",
            evaluator_id="policy",
            dimension="policy",
            metric="policy_match",
            severity=EvaluatorSeverity.BLOCKING,
            failure_stage=FailureStage.FINAL_STATE,
        ),
    )

    clusters = cluster_failed_results(results)

    assert [cluster.failure_count for cluster in clusters] == [3, 1]
    assert clusters[0].case_count == 2
    assert clusters[0].share == 0.75
    assert [member.result_id for member in clusters[0].members] == [
        "result-1",
        "result-2",
        "result-3",
    ]
    assert clusters[0].category == "routing"
    assert clusters[0].label == "Routing: routing/skill_route (routing)"


def test_extracts_unique_sorted_failed_check_span_evidence() -> None:
    first = CheckResult(
        id="check-first",
        name="first",
        outcome=Outcome.FAIL,
        score=0,
        reason="failed",
        span_ids=(SPAN_TWO,),
        failure_stage=FailureStage.ROUTING,
        failure_sequence=1,
        failure_span_id=SPAN_TWO,
    )
    second = CheckResult(
        id="check-second",
        name="second",
        outcome=Outcome.FAIL,
        score=0,
        reason="failed",
        span_ids=(SPAN_ONE, SPAN_TWO),
        failure_stage=FailureStage.ROUTING,
        failure_sequence=2,
        failure_span_id=SPAN_ONE,
    )
    result = failed_result("result-1").model_copy(update={"checks": (first, second)})

    evidence = cluster_failed_results((result,))[0].members[0]

    assert evidence.span_ids == (SPAN_ONE, SPAN_TWO)
    assert evidence.reason == "result-1 failed"
    assert evidence.trace_id == TRACE_ID


def test_limits_representatives_to_first_three_ordered_members() -> None:
    results = tuple(
        failed_result(f"result-{index}", case_id=f"case-{index}")
        for index in range(4, 0, -1)
    )

    cluster = cluster_failed_results(results)[0]

    assert cluster.representative_result_ids == (
        "result-1",
        "result-2",
        "result-3",
    )


def test_input_order_does_not_change_clusters_or_ids() -> None:
    results = (
        failed_result("result-2", case_id="case-2"),
        failed_result("result-1", case_id="case-1"),
        failed_result(
            "result-3",
            evaluator_id="output",
            dimension="answer",
            metric="quality",
            failure_stage=FailureStage.FINAL_OUTPUT,
        ),
    )

    forward = cluster_failed_results(results)
    reverse = cluster_failed_results(tuple(reversed(results)))

    assert forward == reverse
    assert all(cluster.id.startswith("failure-cluster-") for cluster in forward)


def test_equal_sized_clusters_put_blocking_severity_first() -> None:
    standard = failed_result("result-standard")
    blocking = failed_result(
        "result-blocking",
        evaluator_id="policy",
        severity=EvaluatorSeverity.BLOCKING,
        failure_stage=FailureStage.FINAL_STATE,
    )

    clusters = cluster_failed_results((standard, blocking))

    assert clusters[0].severity == EvaluatorSeverity.BLOCKING


def test_empty_input_returns_no_clusters() -> None:
    assert cluster_failed_results(()) == ()


def test_rejects_non_failed_duplicate_and_mixed_run_inputs() -> None:
    failed = failed_result("result-1")
    with pytest.raises(ValueError, match="only failed Results"):
        cluster_failed_results((passing_result("result-pass"),))
    with pytest.raises(ValueError, match="IDs must be unique"):
        cluster_failed_results((failed, failed))
    with pytest.raises(ValueError, match="one Run"):
        cluster_failed_results((
            failed,
            failed_result("result-2", run_id="run-2"),
        ))
