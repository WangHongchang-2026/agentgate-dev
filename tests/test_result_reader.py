from __future__ import annotations

import pytest

from agentgate.application import ResultReader, RunManagement
from agentgate.demo.bootstrap import ensure_demo_dataset
from agentgate.demo.loan import LOAN_DATASET
from agentgate.domain import (
    TargetRef,
    TargetSnapshot,
    TargetType,
)
from agentgate.evaluator import EVALUATORS
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.storage.sqlite import SQLiteRepository


def target() -> TargetSnapshot:
    return TargetSnapshot(
        ref=TargetRef(
            source_id="agentgate-demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id="loan-agent-v2-fixed",
        ),
        display_name="Loan Agent",
        adapter_type="demo_loan",
        adapter_version="1",
        descriptor_sha256="a" * 64,
    )


def completed_run(repository: SQLiteRepository):
    ensure_demo_dataset(repository)
    runs = RunManagement(repository, EVALUATORS)
    run = runs.create_run(target(), dataset_id=LOAN_DATASET.id)
    capture = InMemoryTraceCapture()
    completed = runs.execute_run(
        run.id, DemoLoanTargetAdapter(capture), capture.resolve
    )
    capture.shutdown()
    return completed


def test_reader_builds_report_and_returns_trace(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "reader.db")
    run = completed_run(repository)
    reader = ResultReader(repository)

    report = reader.get_report(run.id)
    trace = reader.get_trace(run.id, "high-risk-approval")

    assert report.run == run
    assert report.release_gate.outcome.value == "pass"
    assert trace.run_id == run.id
    assert reader.list_runs() == [run]


def test_reader_rejects_unknown_and_non_completed_runs(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "reader-errors.db")
    ensure_demo_dataset(repository)
    reader = ResultReader(repository)

    with pytest.raises(LookupError, match="unknown EvaluationRun"):
        reader.get_report("missing")
    with pytest.raises(LookupError, match="unknown EvaluationRun"):
        reader.get_trace("missing", "case")

    pending = RunManagement(repository, EVALUATORS).create_run(
        target(), dataset_id=LOAN_DATASET.id
    )
    with pytest.raises(ValueError, match="completed EvaluationRun"):
        reader.get_report(pending.id)
    with pytest.raises(LookupError, match="unknown Trace"):
        reader.get_trace(pending.id, "missing")


def test_overview_uses_persisted_status_and_dataset_data(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "overview.db")
    completed_run(repository)
    RunManagement(repository, EVALUATORS).create_run(
        target(), dataset_id=LOAN_DATASET.id
    )

    overview = ResultReader(repository).overview()

    assert overview["total_runs"] == 2
    assert overview["pending_runs"] == 1
    assert overview["completed_runs"] == 1
    assert overview["dataset_count"] == 1
    assert overview["case_count"] == 1
    assert overview["latest"].release_gate.outcome.value == "pass"
