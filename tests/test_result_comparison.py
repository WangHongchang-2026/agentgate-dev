from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentgate.domain import (
    Case,
    CaseTurn,
    CheckResult,
    DatasetVersion,
    DatasetVersionStatus,
    EvaluationReport,
    EvaluationResult,
    EvaluationRun,
    EvaluatorSeverity,
    EvaluatorSpec,
    FailureStage,
    MetricPlan,
    Outcome,
    ReleaseGateSpec,
    RunManifest,
    RunStatus,
    TargetRef,
    TargetSnapshot,
    TargetType,
)
from agentgate.result import (
    CaseDelta,
    EvaluationComparison,
    MetricDelta,
    compare_reports,
)
from agentgate.result.report import build_evaluation_report


NOW = datetime(2026, 9, 8, tzinfo=UTC)
TRACE_ID = "a" * 32


def evaluator() -> EvaluatorSpec:
    return EvaluatorSpec(
        id="state",
        name="State",
        dimension="correctness",
        metric="state_match",
        implementation_id="final_state",
    )


def dataset() -> DatasetVersion:
    return DatasetVersion(
        id="dataset-version-1",
        dataset_id="dataset-1",
        dataset_name="Comparison Dataset",
        version=1,
        status=DatasetVersionStatus.PUBLISHED,
        cases=(
            Case(
                id="case-1",
                name="Case 1",
                turns=(CaseTurn(id="turn-1", input={"message": "test"}),),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
        published_at=NOW,
    )


def target(version: str) -> TargetSnapshot:
    return TargetSnapshot(
        ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id=version,
        ),
        display_name="Loan Agent",
        adapter_type="demo",
        adapter_version="1",
        descriptor_sha256="b" * 64,
        captured_at=NOW,
    )


def completed_run(run_id: str, version: str) -> EvaluationRun:
    spec = evaluator()
    return EvaluationRun(
        id=run_id,
        manifest=RunManifest(
            dataset=dataset(),
            target=target(version),
            evaluator_specs=(spec,),
            primary_evaluator_ids=(spec.id,),
            metric_plan=MetricPlan(),
            gate_spec=ReleaseGateSpec(minimum_score=0.5),
            created_at=NOW,
        ),
        status=RunStatus.COMPLETED,
        created_at=NOW,
        started_at=NOW + timedelta(seconds=1),
        completed_at=NOW + timedelta(seconds=2),
    )


def evaluation_result(run_id: str, outcome: Outcome) -> EvaluationResult:
    passed = outcome == Outcome.PASS
    check = CheckResult(
        name="state check",
        outcome=outcome,
        score=1.0 if passed else 0.0,
        reason="matched" if passed else "did not match",
        failure_stage=None if passed else FailureStage.FINAL_STATE,
        failure_sequence=None if passed else 1,
    )
    spec = evaluator()
    return EvaluationResult(
        run_id=run_id,
        case_id="case-1",
        trace_id=TRACE_ID,
        evaluator_id=spec.id,
        evaluator_name=spec.name,
        evaluator_version=spec.version,
        evaluator_content_sha256=spec.content_sha256,
        evaluator_kind=spec.kind,
        dimension=spec.dimension,
        metric=spec.metric,
        severity=EvaluatorSeverity.STANDARD,
        outcome=outcome,
        score=check.score,
        reason=check.reason,
        checks=(check,),
        primary_failure_stage=None if passed else FailureStage.FINAL_STATE,
    )


def reports() -> tuple[EvaluationReport, EvaluationReport]:
    baseline_run = completed_run("baseline-run", "loan-agent-v1-risky")
    candidate_run = completed_run("candidate-run", "loan-agent-v2-fixed")
    baseline = build_evaluation_report(
        baseline_run,
        (evaluation_result(baseline_run.id, Outcome.FAIL),),
    )
    candidate = build_evaluation_report(
        candidate_run,
        (evaluation_result(candidate_run.id, Outcome.PASS),),
    )
    return baseline, candidate


def test_compare_reports_exposes_metric_case_and_gate_changes() -> None:
    baseline, candidate = reports()

    comparison = compare_reports(baseline, candidate)

    assert comparison.baseline_run_id == baseline.run.id
    assert comparison.candidate_run_id == candidate.run.id
    assert comparison.baseline_target_version == "loan-agent-v1-risky"
    assert comparison.candidate_target_version == "loan-agent-v2-fixed"
    assert comparison.baseline_gate.outcome == "fail"
    assert comparison.candidate_gate.outcome == "pass"
    assert comparison.overall_score_delta is not None
    assert comparison.overall_score_delta > 0
    assert any(item.change == "improvement" for item in comparison.case_deltas)
    assert all(item.level == item.baseline.level for item in comparison.metric_deltas)


def test_comparing_one_report_with_itself_is_unchanged() -> None:
    baseline, _ = reports()

    comparison = compare_reports(baseline, baseline)

    assert comparison.overall_score_delta == 0
    assert all(item.score_delta in (None, 0) for item in comparison.metric_deltas)
    assert all(item.change == "unchanged" for item in comparison.case_deltas)


def test_missing_candidate_metric_is_not_treated_as_not_applicable() -> None:
    baseline, candidate = reports()
    removed = candidate.results[0]
    incomplete = build_evaluation_report(
        candidate.run,
        tuple(item for item in candidate.results if item.id != removed.id),
    )

    with pytest.raises(ValueError, match="different metric summaries"):
        compare_reports(baseline, incomplete)


def test_comparison_values_reject_inconsistent_derived_fields() -> None:
    baseline, candidate = reports()
    comparison = compare_reports(baseline, candidate)

    metric_values = comparison.metric_deltas[0].model_dump()
    metric_values["score_delta"] = -1
    with pytest.raises(ValidationError, match="score_delta"):
        MetricDelta(**metric_values)

    case_values = comparison.case_deltas[0].model_dump()
    case_values["change"] = "regression"
    with pytest.raises(ValidationError, match="change"):
        CaseDelta(**case_values)

    values = comparison.model_dump()
    values["metric_deltas"] = (
        comparison.metric_deltas[0],
        *comparison.metric_deltas,
    )
    with pytest.raises(ValidationError, match="metric identities"):
        EvaluationComparison(**values)


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("dataset", "different Dataset content"),
        ("target", "different Agent or Skill targets"),
        ("evaluator", "different primary Evaluators"),
        ("metric_plan", "different Metric plans"),
        ("gate_spec", "different release-gate specifications"),
    ),
)
def test_compare_reports_rejects_incompatible_inputs(
    field: str,
    message: str,
) -> None:
    baseline, candidate = reports()
    manifest = candidate.run.manifest

    if field == "dataset":
        changed = manifest.dataset.model_copy(update={"content_sha256": "a" * 64})
        manifest = manifest.model_copy(update={"dataset": changed})
    elif field == "target":
        changed_ref = manifest.target.ref.model_copy(
            update={"external_target_id": "another-agent"}
        )
        changed = manifest.target.model_copy(update={"ref": changed_ref})
        manifest = manifest.model_copy(update={"target": changed})
    elif field == "evaluator":
        first = manifest.evaluator_specs[0].model_copy(update={"version": "other"})
        manifest = manifest.model_copy(
            update={"evaluator_specs": (first, *manifest.evaluator_specs[1:])}
        )
    elif field == "metric_plan":
        changed = manifest.metric_plan.model_copy(update={"version": "other"})
        manifest = manifest.model_copy(update={"metric_plan": changed})
    else:
        changed = manifest.gate_spec.model_copy(update={"minimum_score": 0.75})
        manifest = manifest.model_copy(update={"gate_spec": changed})

    incompatible_run = candidate.run.model_copy(update={"manifest": manifest})
    incompatible = candidate.model_copy(update={"run": incompatible_run})

    with pytest.raises(ValueError, match=message):
        compare_reports(baseline, incompatible)
