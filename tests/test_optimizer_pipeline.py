from datetime import UTC, datetime, timedelta

import pytest

from agentgate.domain import (
    Case,
    CaseTurn,
    CheckResult,
    DatasetVersion,
    DatasetVersionStatus,
    Equals,
    EvaluationResult,
    EvaluationRun,
    EvaluatorKind,
    EvaluatorSeverity,
    EvaluatorSpec,
    FailureStage,
    FindingSeverity,
    MetricPlan,
    Outcome,
    ReleaseGateSpec,
    RunManifest,
    RunStatus,
    SkillAnalysisFinding,
    SkillRouteExpectation,
    TargetRef,
    TargetSnapshot,
    TargetType,
)
from agentgate.optimizer import build_optimization_report


NOW = datetime(2026, 9, 8, tzinfo=UTC)
TRACE_ID = "a" * 32
SPAN_ID = "b" * 16


def evaluation_case() -> Case:
    return Case(
        id="case-1",
        name="Routing case",
        turns=(
            CaseTurn(
                id="turn-1",
                input={"message": "apply"},
                expectations=(
                    SkillRouteExpectation(
                        id="route-1",
                        condition=Equals(expected="loan"),
                    ),
                ),
            ),
        ),
    )


def run(*, status: RunStatus = RunStatus.COMPLETED) -> EvaluationRun:
    dataset = DatasetVersion(
        id="dataset-version-1",
        dataset_id="dataset-1",
        dataset_name="Dataset",
        version=1,
        status=DatasetVersionStatus.PUBLISHED,
        cases=(evaluation_case(),),
        created_at=NOW,
        updated_at=NOW,
        published_at=NOW,
    )
    target = TargetSnapshot(
        ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id="v1",
        ),
        display_name="Loan Agent",
        adapter_type="python_function",
        adapter_version="1",
        descriptor_sha256="c" * 64,
        captured_at=NOW,
    )
    evaluator = EvaluatorSpec(
        id="routing",
        name="Routing",
        dimension="routing",
        metric="skill_route",
        implementation_id="skill_routing",
    )
    manifest = RunManifest(
        dataset=dataset,
        target=target,
        evaluator_specs=(evaluator,),
        primary_evaluator_ids=(evaluator.id,),
        metric_plan=MetricPlan(),
        gate_spec=ReleaseGateSpec(),
        created_at=NOW,
    )
    if status == RunStatus.PENDING:
        return EvaluationRun(id="run-1", manifest=manifest, created_at=NOW)
    return EvaluationRun(
        id="run-1",
        manifest=manifest,
        status=RunStatus.COMPLETED,
        created_at=NOW,
        started_at=NOW + timedelta(seconds=1),
        completed_at=NOW + timedelta(seconds=2),
    )


def result(
    *,
    actual: str = "loan",
    failed: bool = False,
    run_id: str = "run-1",
) -> EvaluationResult:
    check = CheckResult(
        id="check-1",
        name="route",
        turn_id="turn-1",
        expectation_id="route-1",
        outcome=Outcome.FAIL if failed else Outcome.PASS,
        score=0 if failed else 1,
        reason="wrong route" if failed else "correct route",
        expected={"kind": "equals", "expected": "loan"},
        actual=actual,
        span_ids=(SPAN_ID,),
        failure_stage=FailureStage.ROUTING if failed else None,
        failure_sequence=1 if failed else None,
        failure_span_id=SPAN_ID if failed else None,
    )
    return EvaluationResult(
        id="result-1",
        run_id=run_id,
        case_id="case-1",
        trace_id=TRACE_ID,
        evaluator_id="routing",
        evaluator_name="Routing",
        evaluator_version="1",
        evaluator_content_sha256="d" * 64,
        evaluator_kind=EvaluatorKind.RULE,
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        outcome=Outcome.FAIL if failed else Outcome.PASS,
        score=0 if failed else 1,
        reason="failed" if failed else "passed",
        checks=(check,),
        primary_failure_stage=FailureStage.ROUTING if failed else None,
    )


def static_finding() -> SkillAnalysisFinding:
    return SkillAnalysisFinding(
        id="finding-1",
        check_id="skill_relationships.llm_pairwise",
        category="skill_confusion",
        severity=FindingSeverity.HIGH,
        confidence=0.8,
        skill_ids=("loan", "card"),
        reason="descriptions overlap",
        evidence=({"source": "test"},),
    )


def test_composes_complete_report_with_manifest_provenance() -> None:
    completed = run()

    report = build_optimization_report(
        completed,
        (result(actual="card", failed=True),),
    )

    assert report.run_id == completed.id
    assert report.target_ref == completed.manifest.target.ref
    assert (
        report.target_content_sha256
        == completed.manifest.target.content_sha256
    )
    assert report.dataset_id == completed.manifest.dataset.dataset_id
    assert report.dataset_version == 1
    assert (
        report.dataset_content_sha256
        == completed.manifest.dataset.content_sha256
    )
    assert report.analyzer_version == "1"
    assert report.failed_result_count == 1
    assert len(report.clusters) == 1
    assert report.confusion_matrix.eligible_count == 1
    assert len(report.hypotheses) == 1
    assert len(report.suggestions) == 1


def test_static_findings_flow_into_hypotheses_and_suggestions() -> None:
    finding = static_finding()

    report = build_optimization_report(
        run(),
        (result(actual="card", failed=True),),
        (finding,),
    )

    assert report.hypotheses[0].static_finding_ids == (finding.id,)
    assert report.suggestions[0].target == "skill_routing"


def test_successful_run_has_matrix_without_optimization_output() -> None:
    report = build_optimization_report(run(), (result(),))

    assert report.failed_result_count == 0
    assert report.clusters == ()
    assert report.hypotheses == ()
    assert report.suggestions == ()
    assert report.confusion_matrix.eligible_count == 1
    assert report.confusion_matrix.cells[0].actual_route.skill_id == "loan"


def test_requires_completed_run_and_results_from_that_run() -> None:
    with pytest.raises(ValueError, match="completed EvaluationRun"):
        build_optimization_report(
            run(status=RunStatus.PENDING),
            (),
        )
    with pytest.raises(ValueError, match="requested Run"):
        build_optimization_report(
            run(),
            (result(run_id="another-run"),),
        )


def test_requires_nonblank_analyzer_version() -> None:
    with pytest.raises(ValueError, match="analyzer_version"):
        build_optimization_report(
            run(),
            (result(),),
            analyzer_version=" ",
        )


def test_analytical_content_hash_is_deterministic() -> None:
    completed = run()
    results = (result(actual="card", failed=True),)

    first = build_optimization_report(completed, results)
    second = build_optimization_report(completed, results)

    assert first.content_sha256 == second.content_sha256
    assert first.model_dump(
        mode="json",
        exclude={"created_at"},
    ) == second.model_dump(
        mode="json",
        exclude={"created_at"},
    )
