from __future__ import annotations

import json

import pytest

from agentgate.application import RunManagement
from agentgate.application.evaluator_management import (
    DEFAULT_EVALUATOR_MANAGEMENT,
    build_default_evaluator_management,
)
from agentgate.demo.bootstrap import ensure_demo_dataset
from agentgate.demo.loan import LOAN_DATASET, LOAN_DATASET_VERSION
from agentgate.domain import RunStatus, TargetRef, TargetSnapshot, TargetType
from agentgate.evaluator.judge import JudgeRequest, JudgeResponse
from agentgate.integrations.job_dispatchers.celery import (
    CeleryJobDispatcher,
    create_celery_app,
    execute_evaluation_run,
)
from agentgate.integrations.model_providers.environment import ConfiguredJudgeModel
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.storage.sqlite import SQLiteRepository


class RecordingTask:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def apply_async(self, **kwargs) -> None:
        self.calls.append(kwargs)


class RecordingJudgeClient:
    provider_id = "company-llm"

    def __init__(self) -> None:
        self.requests: list[JudgeRequest] = []
        self.closed = False

    def complete(self, request: JudgeRequest) -> JudgeResponse:
        self.requests.append(request)
        return JudgeResponse(
            text=json.dumps(
                {
                    "verdict": "pass",
                    "score": 0.9,
                    "confidence": 0.95,
                    "reason": "The answer satisfies the rubric",
                    "violations": [],
                }
            ),
            resolved_model_id="resolved-judge-model",
            request_id="judge-request",
        )

    def close(self) -> None:
        self.closed = True


def configured_judge(client: RecordingJudgeClient) -> ConfiguredJudgeModel:
    return ConfiguredJudgeModel(
        provider_id=client.provider_id,
        model_id="judge-model",
        credential_ref="env:AGENTGATE_JUDGE_API_KEY",
        client=client,  # type: ignore[arg-type]
    )


def target() -> TargetSnapshot:
    return TargetSnapshot(
        ref=TargetRef(
            source_id="agentgate-demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id="loan-agent-v2-fixed",
        ),
        display_name="Loan Agent",
        adapter_type=DemoLoanTargetAdapter.adapter_type,
        adapter_version=DemoLoanTargetAdapter.adapter_version,
        descriptor_sha256="a" * 64,
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
    run = RunManagement(repository, DEFAULT_EVALUATOR_MANAGEMENT).create_run(
        target(), dataset_id=LOAN_DATASET.id
    )

    assert execute_evaluation_run.run(run.id) == RunStatus.COMPLETED.value
    completed = repository.get_run(run.id)
    assert completed is not None
    assert completed.status is RunStatus.COMPLETED
    result_count = len(repository.list_results(run.id))
    assert result_count == len(DEFAULT_EVALUATOR_MANAGEMENT.available_specs)

    assert execute_evaluation_run.run(run.id) == RunStatus.COMPLETED.value
    assert len(repository.list_results(run.id)) == result_count


def test_worker_executes_configured_judge_and_closes_client(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "judge-worker.db"
    monkeypatch.setenv("AGENTGATE_DB", str(database_path))
    repository = SQLiteRepository(database_path)
    ensure_demo_dataset(repository)
    client = RecordingJudgeClient()
    configuration = configured_judge(client)
    management = build_default_evaluator_management(
        judge_client=client,
        judge_model_id=configuration.model_id,
        judge_credential_ref=configuration.credential_ref,
    )
    run = RunManagement(repository, management).create_run(
        target(), dataset_id=LOAN_DATASET.id
    )
    monkeypatch.setattr(
        "agentgate.integrations.job_dispatchers.celery."
        "load_judge_model_from_environment",
        lambda: configuration,
    )

    assert execute_evaluation_run.run(run.id) == RunStatus.COMPLETED.value

    assert len(repository.list_results(run.id)) == len(management.available_specs)
    assert len(client.requests) == len(LOAN_DATASET_VERSION.cases)
    assert client.closed is True


def test_worker_closes_judge_client_when_composition_fails(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "judge-composition-failure.db"
    monkeypatch.setenv("AGENTGATE_DB", str(database_path))
    repository = SQLiteRepository(database_path)
    ensure_demo_dataset(repository)
    run = RunManagement(repository, DEFAULT_EVALUATOR_MANAGEMENT).create_run(
        target(), dataset_id=LOAN_DATASET.id
    )
    client = RecordingJudgeClient()
    configuration = configured_judge(client)
    monkeypatch.setattr(
        "agentgate.integrations.job_dispatchers.celery."
        "load_judge_model_from_environment",
        lambda: configuration,
    )

    def fail_composition(**kwargs) -> None:
        del kwargs
        raise ValueError("composition failed")

    monkeypatch.setattr(
        "agentgate.integrations.job_dispatchers.celery."
        "build_default_evaluator_management",
        fail_composition,
    )

    with pytest.raises(ValueError, match="composition failed"):
        execute_evaluation_run.run(run.id)

    assert client.closed is True


def test_worker_rejects_unknown_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTGATE_DB", str(tmp_path / "unknown.db"))

    with pytest.raises(ValueError, match="unknown EvaluationRun"):
        execute_evaluation_run.run("missing")
