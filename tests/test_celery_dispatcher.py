from __future__ import annotations

import pytest

from agentgate.application import RunManagement, TargetCatalog
from agentgate.demo.bootstrap import (
    ensure_demo_dataset,
    ensure_demo_target_descriptors,
)
from agentgate.demo.loan import LOAN_DATASET
from agentgate.demo.targets import (
    build_demo_target_snapshot,
    get_demo_target_descriptor,
)
from agentgate.domain import RunStatus, TargetSnapshot
from agentgate.evaluator import EVALUATORS
from agentgate.integrations.job_dispatchers.celery import (
    CeleryJobDispatcher,
    create_celery_app,
    execute_evaluation_run,
)
from agentgate.storage.sqlite import SQLiteRepository


class RecordingTask:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def apply_async(self, **kwargs) -> None:
        self.calls.append(kwargs)


def target() -> TargetSnapshot:
    return build_demo_target_snapshot(
        get_demo_target_descriptor("loan-agent-v2-fixed")
    )


def test_dispatcher_sends_only_run_id_with_correlated_task_id() -> None:
    task = RecordingTask()
    dispatcher = CeleryJobDispatcher(task=task)  # type: ignore[arg-type]

    dispatcher.submit("run-123")

    assert task.calls == [{"args": ["run-123"], "task_id": "run-123"}]
    with pytest.raises(ValueError, match="run_id must not be blank"):
        dispatcher.submit("  ")


def test_celery_app_uses_json_broker_only_configuration(monkeypatch) -> None:
    monkeypatch.setenv("AGENTGATE_REDIS_URL", "redis://broker.example:6379/4")
    monkeypatch.setenv("AGENTGATE_WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("AGENTGATE_TASK_TIME_LIMIT_SECONDS", "420")

    app = create_celery_app()

    assert app.conf.broker_url == "redis://broker.example:6379/4"
    assert app.conf.result_backend is None
    assert app.conf.accept_content == ["json"]
    assert app.conf.task_serializer == "json"
    assert app.conf.task_ignore_result is True
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is False
    assert app.conf.worker_concurrency == 2
    assert app.conf.task_time_limit == 420


def test_worker_executes_persisted_run_and_duplicate_is_noop(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "worker.db"
    monkeypatch.setenv("AGENTGATE_DB", str(database_path))
    repository = SQLiteRepository(database_path)
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))
    run = RunManagement(repository, EVALUATORS).create_run(
        target(), dataset_id=LOAN_DATASET.id
    )

    assert execute_evaluation_run.run(run.id) == RunStatus.COMPLETED.value
    completed = repository.get_run(run.id)
    assert completed is not None
    assert completed.status is RunStatus.COMPLETED
    result_count = len(repository.list_results(run.id))
    assert result_count == len(EVALUATORS)

    assert execute_evaluation_run.run(run.id) == RunStatus.COMPLETED.value
    assert len(repository.list_results(run.id)) == result_count


def test_worker_rejects_unknown_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTGATE_DB", str(tmp_path / "unknown.db"))

    with pytest.raises(ValueError, match="unknown EvaluationRun"):
        execute_evaluation_run.run("missing")
