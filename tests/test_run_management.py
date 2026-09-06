from __future__ import annotations

from datetime import timedelta

import pytest

from agentgate.application import RunManagement
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


class RecordingDispatcher:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)
        if self.failure is not None:
            raise self.failure


def target(version: str = "loan-agent-v2-fixed") -> TargetSnapshot:
    return TargetSnapshot(
        ref=TargetRef(
            source_id="agentgate-demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id=version,
        ),
        display_name="Loan Agent",
        adapter_type="demo_loan",
        adapter_version="1",
        descriptor_sha256="a" * 64,
        invocation_config={"provider": "deterministic"},
    )


def test_create_run_persists_exact_pending_manifest(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "create-run.db")
    ensure_demo_dataset(repository)
    management = RunManagement(repository, EVALUATORS)

    run = management.create_run(
        target(),
        dataset_id=LOAN_DATASET.id,
        dataset_version=1,
        evaluator_ids=("skill-routing", "final-state"),
        timeout_seconds=30,
    )

    assert run.status is RunStatus.PENDING
    assert repository.get_run(run.id) == run
    assert [spec.id for spec in run.manifest.evaluator_specs] == [
        "skill-routing", "final-state"
    ]
    assert run.manifest.target.ref.external_version_id == "loan-agent-v2-fixed"
    assert run.manifest.timeout_seconds == 30


def test_execute_run_uses_engine_adapter_and_trace_resolver(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "execute-run.db")
    ensure_demo_dataset(repository)
    management = RunManagement(repository, EVALUATORS)
    run = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    capture = InMemoryTraceCapture()
    adapter = DemoLoanTargetAdapter(capture)

    completed = management.execute_run(run.id, adapter, capture.resolve)

    assert completed.status is RunStatus.COMPLETED
    assert len(repository.list_traces(run.id)) == 1
    results = repository.list_results(run.id)
    assert len(results) == len(EVALUATORS)
    assert all(result.outcome.value not in {"fail", "review", "error"}
               for result in results)
    capture.shutdown()


def test_create_run_rejects_unknown_or_duplicate_evaluators(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "invalid-run.db")
    ensure_demo_dataset(repository)
    management = RunManagement(repository, EVALUATORS)

    with pytest.raises(ValueError, match="unknown Evaluators"):
        management.create_run(
            target(), dataset_id=LOAN_DATASET.id, evaluator_ids=("missing",)
        )
    with pytest.raises(ValueError, match="must be unique"):
        management.create_run(
            target(),
            dataset_id=LOAN_DATASET.id,
            evaluator_ids=("final-state", "final-state"),
        )


def test_execute_run_rejects_unknown_run(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "missing-run.db")
    management = RunManagement(repository, EVALUATORS)
    capture = InMemoryTraceCapture()

    with pytest.raises(ValueError, match="unknown EvaluationRun"):
        management.execute_run(
            "missing", DemoLoanTargetAdapter(capture), capture.resolve
        )
    capture.shutdown()


def test_dispatch_run_submits_only_the_persisted_run_id(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "dispatch-run.db")
    ensure_demo_dataset(repository)
    management = RunManagement(repository, EVALUATORS)
    run = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    dispatcher = RecordingDispatcher()

    dispatched = management.dispatch_run(run.id, dispatcher)

    assert dispatched == run
    assert dispatcher.run_ids == [run.id]
    assert repository.get_run(run.id).status is RunStatus.PENDING


def test_dispatch_failure_is_persisted_without_exception_details(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "dispatch-failure.db")
    ensure_demo_dataset(repository)
    management = RunManagement(repository, EVALUATORS)
    run = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    dispatcher = RecordingDispatcher(
        ConnectionError("redis://user:secret@example.invalid")
    )

    with pytest.raises(RuntimeError, match="Run dispatch failed"):
        management.dispatch_run(run.id, dispatcher)

    failed = repository.get_run(run.id)
    assert failed.status is RunStatus.FAILED
    assert failed.error == "Run dispatch failed: ConnectionError"
    assert "secret" not in failed.error


def test_fail_stale_runs_preserves_active_and_pending_runs(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "stale-runs.db")
    ensure_demo_dataset(repository)
    management = RunManagement(repository, EVALUATORS)
    stale = management.create_run(
        target(), dataset_id=LOAN_DATASET.id, timeout_seconds=10
    )
    active = management.create_run(
        target(), dataset_id=LOAN_DATASET.id, timeout_seconds=10
    )
    pending = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    now = max(stale.created_at, active.created_at, pending.created_at) + timedelta(
        seconds=100
    )
    repository.claim_pending_run(stale.id, now - timedelta(seconds=20))
    repository.claim_pending_run(active.id, now - timedelta(seconds=5))

    failed = management.fail_stale_runs(now=now, grace_seconds=5)

    assert [run.id for run in failed] == [stale.id]
    assert repository.get_run(stale.id).status is RunStatus.FAILED
    assert repository.get_run(active.id).status is RunStatus.RUNNING
    assert repository.get_run(pending.id).status is RunStatus.PENDING


def test_fail_stale_runs_rejects_negative_grace_period(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "invalid-grace.db")
    management = RunManagement(repository, EVALUATORS)

    with pytest.raises(ValueError, match="must not be negative"):
        management.fail_stale_runs(grace_seconds=-1)
