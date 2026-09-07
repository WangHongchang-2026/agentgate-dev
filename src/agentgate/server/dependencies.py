"""Process-lifetime dependencies used by AgentGate HTTP routes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request

from agentgate.application import DatasetManagement, ResultReader, RunManagement
from agentgate.demo.bootstrap import ensure_demo_dataset
from agentgate.demo.loan import LOAN_DATASET, LoanAgent
from agentgate.domain import (
    EvaluationRun,
    TargetRef,
    TargetSnapshot,
    TargetType,
    content_sha256,
)
from agentgate.evaluator import EVALUATORS
from agentgate.integrations.job_dispatchers import JobDispatcher
from agentgate.integrations.job_dispatchers.celery import CeleryJobDispatcher
from agentgate.integrations.observability import (
    InMemoryTraceCapture,
    ingest_otlp_http_json,
)
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.storage.sqlite import SQLiteRepository


@dataclass(slots=True)
class ServerDependencies:
    """Explicit application and infrastructure dependencies for one FastAPI app."""

    repository: SQLiteRepository
    datasets: DatasetManagement
    runs: RunManagement
    results: ResultReader
    dispatcher: JobDispatcher
    demo_state: dict[str, dict]

    def ingest_otlp_json(self, payload: dict[str, Any]) -> int:
        """Normalize and persist one external OTLP/HTTP JSON payload."""

        return ingest_otlp_http_json(payload, self.repository)

    def submit_demo_run(
        self,
        version: str,
        *,
        dataset_id: str = LOAN_DATASET.id,
        dataset_version: int | None = None,
        evaluator_ids: list[str] | None = None,
    ) -> EvaluationRun:
        """Create and asynchronously dispatch one POC Loan Agent evaluation."""

        run = self._create_demo_run(
            version,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            evaluator_ids=evaluator_ids,
        )
        return self.runs.dispatch_run(run.id, self.dispatcher)

    def execute_demo_run(
        self,
        version: str,
        *,
        dataset_id: str = LOAN_DATASET.id,
        dataset_version: int | None = None,
        evaluator_ids: list[str] | None = None,
    ) -> EvaluationRun:
        """Create and synchronously execute one POC Loan Agent evaluation."""

        run = self._create_demo_run(
            version,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            evaluator_ids=evaluator_ids,
        )
        capture = InMemoryTraceCapture()
        try:
            adapter = DemoLoanTargetAdapter(
                capture, state_store=self.demo_state
            )
            return self.runs.execute_run(run.id, adapter, capture.resolve)
        finally:
            capture.shutdown()

    def _create_demo_run(
        self,
        version: str,
        *,
        dataset_id: str,
        dataset_version: int | None,
        evaluator_ids: list[str] | None,
    ) -> EvaluationRun:
        if version not in LoanAgent.versions:
            raise ValueError(f"unknown demo Target version: {version}")
        return self.runs.create_run(
            _demo_target(version),
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            evaluator_ids=evaluator_ids,
        )


def get_dependencies(request: Request) -> ServerDependencies:
    """Return the typed dependency container owned by the FastAPI app."""

    dependencies = getattr(request.app.state, "dependencies", None)
    if not isinstance(dependencies, ServerDependencies):
        raise RuntimeError("AgentGate server dependencies are not configured")
    return dependencies


def build_dependencies(
    database_path: str | Path | None = None,
    dispatcher: JobDispatcher | None = None,
) -> ServerDependencies:
    """Build isolated dependencies for one AgentGate FastAPI application."""

    path = database_path or os.getenv("AGENTGATE_DB", "agentgate.db")
    repository = SQLiteRepository(path)
    ensure_demo_dataset(repository)
    return ServerDependencies(
        repository=repository,
        datasets=DatasetManagement(repository),
        runs=RunManagement(repository, EVALUATORS),
        results=ResultReader(repository),
        dispatcher=dispatcher or CeleryJobDispatcher(),
        demo_state={},
    )


def _demo_target(version: str) -> TargetSnapshot:
    return TargetSnapshot(
        ref=TargetRef(
            source_id="agentgate-demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id=version,
        ),
        display_name="Loan Agent",
        adapter_type=DemoLoanTargetAdapter.adapter_type,
        adapter_version=DemoLoanTargetAdapter.adapter_version,
        descriptor_sha256=content_sha256({
            "name": "loan-agent",
            "versions": LoanAgent.versions,
        }),
        invocation_config={"provider": "deterministic"},
    )
