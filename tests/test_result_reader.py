from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from agentgate.application import ResultReader, RunManagement
from agentgate.demo.bootstrap import ensure_demo_dataset
from agentgate.demo.loan import LOAN_DATASET
from agentgate.domain import (
    RunStatus,
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


def test_reader_derives_complete_case_progress_from_result_sets(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "progress.db")
    source = completed_run(repository)
    management = RunManagement(repository, EVALUATORS)
    pending = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    running = repository.claim_pending_run(
        pending.id, pending.created_at + timedelta(seconds=2)
    )
    assert running is not None
    source_trace = repository.get_trace(source.id, "high-risk-approval")
    assert source_trace is not None
    trace_id = uuid4().hex
    trace_payload = source_trace.model_dump(mode="json")
    trace_payload.update({"trace_id": trace_id, "run_id": running.id})
    trace_payload["spans"] = [
        {**span, "trace_id": trace_id}
        for span in trace_payload["spans"]
    ]
    repository.save_trace(type(source_trace).model_validate(trace_payload))
    source_results = repository.list_results(source.id)

    def copy_result(index: int):
        payload = source_results[index].model_dump(mode="json")
        payload.update(
            {"id": str(uuid4()), "run_id": running.id, "trace_id": trace_id}
        )
        return type(source_results[index]).model_validate(payload)

    repository.save_results([copy_result(0)])
    reader = ResultReader(repository)

    partial = reader.get_run_progress(
        running.id, now=running.started_at + timedelta(seconds=3)
    )

    assert partial.status is RunStatus.RUNNING
    assert partial.total_cases == 1
    assert partial.completed_cases == 0
    assert partial.progress == 0
    assert partial.duration_seconds == 3

    repository.save_results(
        [copy_result(index) for index in range(1, len(source_results))]
    )
    complete = reader.get_run_progress(running.id)

    assert complete.completed_cases == 1
    assert complete.progress == 1


def test_reader_projects_queue_activity_and_terminal_history(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "activity.db")
    terminal = completed_run(repository)
    management = RunManagement(repository, EVALUATORS)
    first = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    second = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    running = repository.claim_pending_run(
        second.id, second.created_at + timedelta(seconds=1)
    )
    assert running is not None
    now = running.started_at + timedelta(seconds=4)

    reader = ResultReader(repository)
    activity = reader.activity(now=now)

    assert activity.status_counts[RunStatus.PENDING] == 1
    assert activity.status_counts[RunStatus.RUNNING] == 1
    assert activity.status_counts[RunStatus.COMPLETED] == 1
    assert [item.run_id for item in activity.queued] == [first.id]
    assert activity.queued[0].queue_position == 1
    assert [item.run_id for item in activity.running] == [running.id]
    assert activity.running[0].duration_seconds == 4
    assert [item.run_id for item in activity.recent] == [terminal.id]
    assert reader.get_run_progress(first.id).queue_position == 1
    assert reader.list_runs(status=RunStatus.RUNNING) == [running]


def test_overview_counts_all_runs_beyond_history_page(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "uncapped-overview.db")
    ensure_demo_dataset(repository)
    management = RunManagement(repository, EVALUATORS)
    for _ in range(51):
        management.create_run(target(), dataset_id=LOAN_DATASET.id)

    overview = ResultReader(repository).overview()

    assert overview["total_runs"] == 51
    assert overview["pending_runs"] == 51
