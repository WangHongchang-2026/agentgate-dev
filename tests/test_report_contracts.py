import pytest
from pydantic import ValidationError

from agentgate.control_plane import EvaluationService
from agentgate.domain import EvaluationReport
from agentgate.result.report import build_evaluation_report
from agentgate.storage.sqlite import SQLiteRepository


def completed_report(tmp_path):
    service = EvaluationService(SQLiteRepository(tmp_path / "report-contracts.db"))
    run = service.launch("loan-agent-v2-fixed")
    return run, service.run_detail(run.id)


def test_empty_results_produce_a_fail_closed_report(tmp_path):
    run, _ = completed_report(tmp_path)

    report = build_evaluation_report(run, ())

    assert report.results == ()
    assert report.metrics[0].total == 0
    assert report.release_gate.reason_code == "missing_results"
    assert len(report.release_gate.missing_results) == (
        len(run.manifest.dataset.cases)
        * len(run.manifest.primary_evaluator_ids)
    )


def test_report_rejects_overall_metric_counts_that_drift_from_results(tmp_path):
    _, report = completed_report(tmp_path)
    overall = report.metrics[0].model_copy(
        update={
            "passed": report.metrics[0].passed + 1,
            "applicable": report.metrics[0].applicable + 1,
            "total": report.metrics[0].total + 1,
        }
    )

    with pytest.raises(ValidationError, match="counts do not match"):
        EvaluationReport(
            run=report.run,
            results=report.results,
            metrics=(overall, *report.metrics[1:]),
            release_gate=report.release_gate,
        )


def test_report_rejects_gate_reason_that_does_not_match_results(tmp_path):
    _, report = completed_report(tmp_path)
    changed_gate = report.release_gate.model_copy(
        update={"outcome": "fail", "reason_code": "blocking_failure"}
    )

    with pytest.raises(ValidationError, match="decision does not match"):
        EvaluationReport(
            run=report.run,
            results=report.results,
            metrics=report.metrics,
            release_gate=changed_gate,
        )
