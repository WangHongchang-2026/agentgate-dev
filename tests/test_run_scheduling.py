from __future__ import annotations

from datetime import timedelta

from agentgate.application import RunManagement, RunScheduling, TargetCatalog
from agentgate.application.evaluator_management import (
    build_default_evaluator_management,
)
from agentgate.demo.bootstrap import (
    ensure_demo_dataset,
    ensure_demo_target_descriptors,
)
from agentgate.demo.loan import LOAN_DATASET
from agentgate.demo.targets import (
    build_demo_target_snapshot,
    get_demo_target_descriptor,
)
from agentgate.domain import RunStatus, utcnow
from agentgate.storage.sqlite import SQLiteRepository


class RecordingDispatcher:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)
        if self.failure is not None:
            raise self.failure

    def cancel(self, run_id: str) -> None:
        del run_id


def create_scheduled_run(
    repository: SQLiteRepository,
    *,
    scheduled_for,
):
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))
    management = RunManagement(
        repository,
        build_default_evaluator_management(repository),
    )
    target = build_demo_target_snapshot(
        get_demo_target_descriptor("loan-agent-v2-fixed")
    )
    return management.create_run(
        target,
        dataset_id=LOAN_DATASET.id,
        scheduled_for=scheduled_for,
    )


def test_repository_atomically_releases_only_due_scheduled_runs(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "scheduled-runs.db")
    scheduled_for = utcnow() + timedelta(hours=1)
    run = create_scheduled_run(repository, scheduled_for=scheduled_for)

    assert run.status is RunStatus.SCHEDULED
    assert repository.claim_due_scheduled_runs(
        scheduled_for - timedelta(seconds=1)
    ) == []

    claimed = repository.claim_due_scheduled_runs(scheduled_for)

    assert [item.id for item in claimed] == [run.id]
    assert claimed[0].status is RunStatus.PENDING
    assert claimed[0].scheduled_for == scheduled_for
    assert repository.claim_due_scheduled_runs(scheduled_for) == []


def test_scheduling_dispatches_each_due_run_once(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "dispatch-due.db")
    scheduled_for = utcnow() + timedelta(hours=1)
    run = create_scheduled_run(repository, scheduled_for=scheduled_for)
    dispatcher = RecordingDispatcher()
    scheduling = RunScheduling(repository)

    dispatched = scheduling.dispatch_due_runs(
        dispatcher,
        now=scheduled_for,
    )
    repeated = scheduling.dispatch_due_runs(
        dispatcher,
        now=scheduled_for,
    )

    assert [item.id for item in dispatched] == [run.id]
    assert repeated == ()
    assert dispatcher.run_ids == [run.id]
    assert repository.get_run(run.id).status is RunStatus.PENDING


def test_scheduling_records_sanitized_dispatch_failure(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "scheduled-failure.db")
    scheduled_for = utcnow() + timedelta(hours=1)
    run = create_scheduled_run(repository, scheduled_for=scheduled_for)

    dispatched = RunScheduling(repository).dispatch_due_runs(
        RecordingDispatcher(ConnectionError("redis password=secret")),
        now=scheduled_for,
    )

    failed = repository.get_run(run.id)
    assert dispatched == ()
    assert failed.status is RunStatus.FAILED
    assert failed.error == "Run dispatch failed: ConnectionError"
    assert "secret" not in failed.error


def test_scheduled_run_can_be_cancelled_before_release(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "cancel-scheduled.db")
    run = create_scheduled_run(
        repository,
        scheduled_for=utcnow() + timedelta(hours=1),
    )

    cancelled = repository.cancel_run(run.id, run.created_at)

    assert cancelled is not None
    assert cancelled.status is RunStatus.CANCELLED
    assert repository.claim_due_scheduled_runs(run.scheduled_for) == []
