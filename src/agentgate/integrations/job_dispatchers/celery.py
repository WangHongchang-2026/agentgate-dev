"""Celery/Redis delivery for persisted Evaluation Runs."""

from __future__ import annotations

import os
from pathlib import Path

from celery import Celery
from celery.app.task import Task

from agentgate.application import RunManagement
from agentgate.domain import RunStatus
from agentgate.evaluator import EVALUATORS
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.storage.sqlite import SQLiteRepository


TASK_NAME = "agentgate.execute_evaluation_run"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_TASK_TIME_LIMIT_SECONDS = 360


def _positive_int_setting(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


def create_celery_app() -> Celery:
    """Build the process-local Celery application from environment settings."""

    app = Celery(
        "agentgate",
        broker=os.getenv("AGENTGATE_REDIS_URL", DEFAULT_REDIS_URL),
    )
    app.conf.update(
        accept_content=["json"],
        result_backend=None,
        result_serializer="json",
        task_acks_late=True,
        task_ignore_result=True,
        task_reject_on_worker_lost=False,
        task_serializer="json",
        task_store_errors_even_if_ignored=False,
        task_time_limit=_positive_int_setting(
            "AGENTGATE_TASK_TIME_LIMIT_SECONDS",
            DEFAULT_TASK_TIME_LIMIT_SECONDS,
        ),
        worker_concurrency=_positive_int_setting(
            "AGENTGATE_WORKER_CONCURRENCY", 1
        ),
    )
    return app


celery_app = create_celery_app()


@celery_app.task(
    name=TASK_NAME,
    acks_late=True,
    ignore_result=True,
    reject_on_worker_lost=False,
)
def execute_evaluation_run(run_id: str) -> str:
    """Load one persisted Run and execute it through the shared application boundary."""

    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must not be blank")
    repository = SQLiteRepository(
        Path(os.getenv("AGENTGATE_DB", "agentgate.db"))
    )
    run = repository.get_run(run_id)
    if run is None:
        raise ValueError(f"unknown EvaluationRun: {run_id}")
    if run.status is not RunStatus.PENDING:
        return run.status.value
    if run.manifest.target.adapter_type != DemoLoanTargetAdapter.adapter_type:
        raise ValueError(
            "Celery worker does not support the Run Target adapter type"
        )

    capture = InMemoryTraceCapture()
    try:
        completed = RunManagement(repository, EVALUATORS).execute_run(
            run.id,
            DemoLoanTargetAdapter(capture),
            capture.resolve,
        )
    finally:
        capture.shutdown()
    return completed.status.value


class CeleryJobDispatcher:
    """Submit persisted Run IDs to the configured Celery broker."""

    def __init__(self, task: Task | None = None) -> None:
        self.task = task or execute_evaluation_run

    def submit(self, run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must not be blank")
        self.task.apply_async(args=[run_id], task_id=run_id)
