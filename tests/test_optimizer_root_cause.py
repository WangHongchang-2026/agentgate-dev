import pytest

from agentgate.domain import (
    FailedResultEvidence,
    FailureCluster,
    FailureStage,
    FindingSeverity,
    ObservedRoute,
    ObservedRouteKind,
    RoutingConfusionCell,
    RoutingConfusionMatrix,
    RoutingObservation,
    SkillAnalysisFinding,
)
from agentgate.optimizer.root_cause import infer_root_causes


TRACE_ID = "a" * 32
SPAN_ID = "b" * 16


def evidence(
    result_id: str,
    *,
    case_id: str = "case-1",
    failure_stage: FailureStage = FailureStage.FINAL_OUTPUT,
    span_ids: tuple[str, ...] = (SPAN_ID,),
) -> FailedResultEvidence:
    return FailedResultEvidence(
        run_id="run-1",
        case_id=case_id,
        result_id=result_id,
        trace_id=TRACE_ID,
        evaluator_id="evaluator",
        dimension="answer",
        metric="quality",
        severity="standard",
        failure_stage=failure_stage,
        reason="failed",
        span_ids=span_ids,
    )


def cluster(
    cluster_id: str,
    *members: FailedResultEvidence,
    failure_stage: FailureStage = FailureStage.FINAL_OUTPUT,
) -> FailureCluster:
    return FailureCluster(
        id=cluster_id,
        category=failure_stage.value,
        label="Failure",
        failure_stage=failure_stage,
        evaluator_id="evaluator",
        dimension="answer",
        metric="quality",
        severity="standard",
        members=members,
        representative_result_ids=(members[0].result_id,),
        failure_count=len(members),
        case_count=len({member.case_id for member in members}),
        share=1,
    )


def observation(
    result_id: str,
    *,
    expected: str = "loan",
    actual: str | None = "card",
    kind: ObservedRouteKind = ObservedRouteKind.SKILL,
) -> RoutingObservation:
    return RoutingObservation(
        case_id="case-1",
        turn_id="turn-1",
        expectation_id="expectation-1",
        result_id=result_id,
        trace_id=TRACE_ID,
        expected_skill_id=expected,
        actual_route=ObservedRoute(kind=kind, skill_id=actual),
        span_ids=(SPAN_ID,),
    )


def matrix(*observations: RoutingObservation) -> RoutingConfusionMatrix:
    cells = tuple(
        RoutingConfusionCell(
            expected_skill_id=item.expected_skill_id,
            actual_route=item.actual_route,
            observations=(item,),
            count=1,
        )
        for item in observations
    )
    return RoutingConfusionMatrix(
        cells=cells,
        eligible_count=len(observations),
    )


def finding(
    finding_id: str,
    *skill_ids: str,
    confidence: float = 0.8,
) -> SkillAnalysisFinding:
    return SkillAnalysisFinding(
        id=finding_id,
        check_id="skill_relationships.llm_pairwise",
        category="skill_confusion",
        severity=FindingSeverity.HIGH,
        confidence=confidence,
        skill_ids=skill_ids,
        reason="descriptions overlap",
        evidence=({"source": "test"},),
    )


def test_builds_generic_hypothesis_from_cluster_evidence() -> None:
    failure_cluster = cluster(
        "cluster-output",
        evidence("result-2", case_id="case-2"),
        evidence("result-1"),
    )

    hypothesis = infer_root_causes(
        (failure_cluster,),
        matrix(),
    )[0]

    assert hypothesis.category == "final_output_failure"
    assert hypothesis.title == "Possible final output failure pattern"
    assert hypothesis.cluster_ids == ("cluster-output",)
    assert hypothesis.result_ids == ("result-1", "result-2")
    assert hypothesis.span_ids == (SPAN_ID,)
    assert hypothesis.confidence == 0.65
    assert hypothesis.explanation.startswith("Hypothesis:")


def test_routing_mismatch_and_static_finding_corroborate_hypothesis() -> None:
    route_evidence = evidence(
        "result-1",
        failure_stage=FailureStage.ROUTING,
    )
    route_cluster = cluster(
        "cluster-routing",
        route_evidence,
        failure_stage=FailureStage.ROUTING,
    )

    hypothesis = infer_root_causes(
        (route_cluster,),
        matrix(observation("result-1")),
        (
            finding("finding-related", "loan", "card"),
            finding("finding-unrelated", "payments"),
        ),
    )[0]

    assert hypothesis.category == "routing_confusion"
    assert hypothesis.title == "Possible Skill-routing confusion"
    assert hypothesis.static_finding_ids == ("finding-related",)
    assert hypothesis.confidence == 0.72
    assert "incorrect routing observations" in hypothesis.explanation
    assert "static Skill findings" in hypothesis.explanation


def test_correct_route_does_not_corroborate_routing_failure() -> None:
    route_cluster = cluster(
        "cluster-routing",
        evidence("result-1", failure_stage=FailureStage.ROUTING),
        failure_stage=FailureStage.ROUTING,
    )
    correct = observation("result-1", expected="loan", actual="loan")

    hypothesis = infer_root_causes(
        (route_cluster,),
        matrix(correct),
        (finding("finding-1", "loan"),),
    )[0]

    assert hypothesis.category == "routing_failure"
    assert hypothesis.static_finding_ids == ()
    assert hypothesis.confidence == 0.45


def test_missing_route_is_incorrect_without_static_skill_match() -> None:
    route_cluster = cluster(
        "cluster-routing",
        evidence(
            "result-1",
            failure_stage=FailureStage.ROUTING,
            span_ids=(),
        ),
        failure_stage=FailureStage.ROUTING,
    )
    missing = observation(
        "result-1",
        actual=None,
        kind=ObservedRouteKind.MISSING,
    )

    hypothesis = infer_root_causes(
        (route_cluster,),
        matrix(missing),
    )[0]

    assert hypothesis.category == "routing_confusion"
    assert hypothesis.confidence == 0.5


def test_output_is_deterministic_and_ordered_by_confidence() -> None:
    weak = cluster(
        "cluster-weak",
        evidence("result-weak", span_ids=()),
    )
    strong = cluster(
        "cluster-strong",
        evidence("result-2", case_id="case-2"),
        evidence("result-1"),
    )

    forward = infer_root_causes((weak, strong), matrix())
    reverse = infer_root_causes((strong, weak), matrix())

    assert forward == reverse
    assert forward[0].cluster_ids == ("cluster-strong",)
    assert all(item.id.startswith("root-cause-") for item in forward)


def test_empty_clusters_return_no_hypotheses() -> None:
    assert infer_root_causes((), matrix()) == ()


def test_rejects_duplicate_cluster_result_and_static_finding_ids() -> None:
    first = cluster("cluster-1", evidence("result-1"))
    second_cluster_id = cluster("cluster-1", evidence("result-2"))
    repeated_result = cluster("cluster-2", evidence("result-1"))
    static_finding = finding("finding-1", "loan")

    with pytest.raises(ValueError, match="cluster IDs must be unique"):
        infer_root_causes((first, second_cluster_id), matrix())
    with pytest.raises(ValueError, match="exactly one root-cause cluster"):
        infer_root_causes((first, repeated_result), matrix())
    with pytest.raises(ValueError, match="finding IDs must be unique"):
        infer_root_causes(
            (first,),
            matrix(),
            (static_finding, static_finding),
        )
