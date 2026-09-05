import pytest
from pydantic import ValidationError

from agentgate.control_plane import EvaluationService
from agentgate.domain import EvaluationReport, RunStatus
from agentgate.result.report import build_evaluation_report
from agentgate.storage.sqlite import SQLiteRepository


def completed_report(tmp_path):
    repository = SQLiteRepository(tmp_path / "report.db")
    service = EvaluationService(repository)
    run = service.launch("loan-agent-v2-fixed")
    report = service.run_detail(run.id)
    return repository, run, report


def test_report_assembles_one_consistent_completed_run(tmp_path):
    _, run, report = completed_report(tmp_path)

    assert isinstance(report, EvaluationReport)
    assert report.run.id == run.id
    assert report.release_gate.outcome == "pass"
    assert report.release_gate.score == report.metrics[0].score
    assert report.release_gate.missing_results == ()


def test_report_rejects_foreign_and_duplicate_results(tmp_path):
    _, _, report = completed_report(tmp_path)
    foreign = report.results[0].model_copy(update={"run_id": "another-run"})
    with pytest.raises(ValidationError, match="different Run"):
        EvaluationReport(
            run=report.run,
            results=(foreign, *report.results[1:]),
            metrics=report.metrics,
            release_gate=report.release_gate,
        )

    with pytest.raises(ValidationError, match="unique by Case and Evaluator"):
        EvaluationReport(
            run=report.run,
            results=(*report.results, report.results[0]),
            metrics=report.metrics,
            release_gate=report.release_gate,
        )


def test_report_rejects_evaluator_and_gate_drift(tmp_path):
    _, _, report = completed_report(tmp_path)
    changed = report.results[0].model_copy(update={"evaluator_version": "other"})
    with pytest.raises(ValidationError, match="RunManifest Evaluator"):
        EvaluationReport(
            run=report.run,
            results=(changed, *report.results[1:]),
            metrics=report.metrics,
            release_gate=report.release_gate,
        )

    changed_gate = report.release_gate.model_copy(update={"score": 0.99})
    with pytest.raises(ValidationError, match="overall Metric score"):
        EvaluationReport(
            run=report.run,
            results=report.results,
            metrics=report.metrics,
            release_gate=changed_gate,
        )


def test_missing_result_produces_valid_fail_closed_report(tmp_path):
    repository, run, report = completed_report(tmp_path)
    partial = build_evaluation_report(run, report.results[1:])

    assert partial.release_gate.outcome == "fail"
    assert partial.release_gate.missing_results == ((
        run.manifest.dataset.cases[0].id,
        report.results[0].evaluator_id,
    ),)
    assert repository.get_run(run.id).status == RunStatus.COMPLETED


def test_report_requires_completed_run(tmp_path):
    _, _, report = completed_report(tmp_path)
    running = report.run.model_copy(update={"status": RunStatus.PENDING, "started_at": None, "completed_at": None})
    with pytest.raises(ValidationError, match="completed EvaluationRun"):
        EvaluationReport(
            run=running,
            results=report.results,
            metrics=report.metrics,
            release_gate=report.release_gate,
        )
