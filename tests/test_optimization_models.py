from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentgate.domain.evaluator import EvaluatorSeverity
from agentgate.domain import (
    FailedResultEvidence,
    FailureCluster,
    ObservedRoute,
    ObservedRouteKind,
    OptimizationReport,
    OptimizationSuggestion,
    RootCauseHypothesis,
    RoutingConfusionCell,
    RoutingConfusionMatrix,
    RoutingExclusion,
    RoutingObservation,
    SuggestionPriority,
)
from agentgate.domain.result import FailureStage
from agentgate.domain.target import TargetRef, TargetType


NOW = datetime(2026, 9, 8, tzinfo=UTC)
TRACE_ID = "a" * 32
SPAN_ID = "b" * 16


def evidence(result_id: str = "result-1", case_id: str = "case-1") -> FailedResultEvidence:
    return FailedResultEvidence(
        run_id="run-1",
        case_id=case_id,
        result_id=result_id,
        trace_id=TRACE_ID,
        evaluator_id="skill-routing",
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.BLOCKING,
        failure_stage=FailureStage.ROUTING,
        reason="selected the wrong Skill",
        span_ids=(SPAN_ID,),
    )


def cluster() -> FailureCluster:
    members = (evidence(), evidence("result-2", "case-2"))
    return FailureCluster(
        id="cluster-routing",
        category="routing_confusion",
        label="Skill routing confusion",
        failure_stage=FailureStage.ROUTING,
        evaluator_id="skill-routing",
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.BLOCKING,
        members=members,
        representative_result_ids=(members[0].result_id,),
        failure_count=2,
        case_count=2,
        share=1,
    )


def observation() -> RoutingObservation:
    return RoutingObservation(
        case_id="case-1",
        turn_id="turn-1",
        expectation_id="expectation-1",
        result_id="result-1",
        trace_id=TRACE_ID,
        expected_skill_id="loan_approval",
        actual_route=ObservedRoute(
            kind=ObservedRouteKind.SKILL,
            skill_id="credit_inquiry",
        ),
        span_ids=(SPAN_ID,),
    )


def matrix() -> RoutingConfusionMatrix:
    item = observation()
    return RoutingConfusionMatrix(
        cells=(
            RoutingConfusionCell(
                expected_skill_id=item.expected_skill_id,
                actual_route=item.actual_route,
                observations=(item,),
                count=1,
            ),
        ),
        eligible_count=1,
        exclusions=(
            RoutingExclusion(
                case_id="case-2",
                turn_id="turn-2",
                expectation_id="expectation-2",
                reason="expected route is not one exact Skill ID",
            ),
        ),
    )


def hypothesis() -> RootCauseHypothesis:
    return RootCauseHypothesis(
        id="hypothesis-1",
        category="skill_boundary_overlap",
        title="Skill boundaries may overlap",
        explanation="Observed routing repeatedly selected the adjacent Skill.",
        confidence=0.8,
        cluster_ids=("cluster-routing",),
        result_ids=("result-1",),
        span_ids=(SPAN_ID,),
        static_finding_ids=("finding-1",),
    )


def suggestion() -> OptimizationSuggestion:
    return OptimizationSuggestion(
        id="suggestion-1",
        target="skill_description",
        target_id="loan_approval",
        priority=SuggestionPriority.HIGH,
        title="Clarify the loan approval boundary",
        recommendation="State when credit inquiry must not be selected.",
        rationale="Two Cases selected the adjacent Skill.",
        hypothesis_ids=("hypothesis-1",),
    )


def report() -> OptimizationReport:
    return OptimizationReport(
        run_id="run-1",
        target_ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id="v1",
        ),
        target_content_sha256="c" * 64,
        dataset_id="dataset-1",
        dataset_version=1,
        dataset_content_sha256="d" * 64,
        analyzer_version="1",
        failed_result_count=2,
        clusters=(cluster(),),
        confusion_matrix=matrix(),
        hypotheses=(hypothesis(),),
        suggestions=(suggestion(),),
        created_at=NOW,
    )


def test_optimization_report_accepts_consistent_evidence_and_hashes_content() -> None:
    value = report()

    assert len(value.content_sha256) == 64
    assert value.clusters[0].failure_count == 2
    assert value.confusion_matrix.eligible_count == 1
    assert value.suggestions[0].requires_human_review is True


def test_failure_cluster_rejects_inconsistent_counts_and_members() -> None:
    valid = cluster()
    values = valid.model_dump()
    values["failure_count"] = 1
    with pytest.raises(ValidationError, match="failure_count"):
        FailureCluster(**values)

    values = valid.model_dump()
    values["representative_result_ids"] = ("missing-result",)
    with pytest.raises(ValidationError, match="belong to the cluster"):
        FailureCluster(**values)


def test_observed_route_requires_exact_skill_only_for_skill_bucket() -> None:
    with pytest.raises(ValidationError, match="requires skill_id"):
        ObservedRoute(kind=ObservedRouteKind.SKILL)

    with pytest.raises(ValidationError, match="cannot contain skill_id"):
        ObservedRoute(kind=ObservedRouteKind.MISSING, skill_id="loan_approval")


def test_confusion_matrix_reconciles_cells_and_exclusions() -> None:
    valid = matrix()
    with pytest.raises(ValidationError, match="eligible_count"):
        RoutingConfusionMatrix(
            cells=valid.cells,
            eligible_count=2,
            exclusions=valid.exclusions,
        )

    item = observation()
    overlapping = RoutingExclusion(
        case_id=item.case_id,
        turn_id=item.turn_id,
        expectation_id=item.expectation_id,
        reason="must not overlap",
    )
    with pytest.raises(ValidationError, match="eligible and excluded"):
        RoutingConfusionMatrix(
            cells=valid.cells,
            eligible_count=1,
            exclusions=(overlapping,),
        )


def test_report_rejects_cross_cluster_result_duplication() -> None:
    valid = report()
    duplicate = valid.clusters[0].model_copy(
        update={"id": "cluster-duplicate", "share": 0.5}
    )
    first = valid.clusters[0].model_copy(update={"share": 0.5})

    with pytest.raises(ValidationError, match="exactly one cluster"):
        OptimizationReport.model_validate(
            {
                **valid.model_dump(mode="json"),
                "failed_result_count": 4,
                "clusters": (first, duplicate),
                "content_sha256": "",
            }
        )


def test_report_rejects_unknown_hypothesis_references() -> None:
    valid = report()
    invalid_hypothesis = valid.hypotheses[0].model_copy(
        update={"cluster_ids": ("unknown-cluster",)}
    )
    with pytest.raises(ValidationError, match="unknown failure cluster"):
        OptimizationReport.model_validate(
            {
                **valid.model_dump(mode="json"),
                "hypotheses": (invalid_hypothesis,),
                "content_sha256": "",
            }
        )

    invalid_suggestion = valid.suggestions[0].model_copy(
        update={"hypothesis_ids": ("unknown-hypothesis",)}
    )
    with pytest.raises(ValidationError, match="unknown root-cause hypothesis"):
        OptimizationReport.model_validate(
            {
                **valid.model_dump(mode="json"),
                "suggestions": (invalid_suggestion,),
                "content_sha256": "",
            }
        )


def test_empty_success_report_rejects_optimization_output() -> None:
    valid = report()
    with pytest.raises(ValidationError, match="without failed Results"):
        OptimizationReport.model_validate(
            {
                **valid.model_dump(mode="json"),
                "failed_result_count": 0,
                "content_sha256": "",
            }
        )


def test_report_rejects_tampered_content_hash() -> None:
    values = report().model_dump(mode="json")
    values["content_sha256"] = "f" * 64

    with pytest.raises(ValidationError, match="content hash mismatch"):
        OptimizationReport.model_validate(values)
