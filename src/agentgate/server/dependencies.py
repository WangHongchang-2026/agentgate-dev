"""Process-lifetime dependencies used by AgentGate HTTP routes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Request

from agentgate.application import (
    DatasetManagement,
    LineageQueries,
    ResultReader,
    RunManagement,
    TargetCatalog,
)
from agentgate.application.evaluator_management import (
    EvaluatorManagement,
    build_default_evaluator_management,
)
from agentgate.demo.bootstrap import (
    ensure_demo_dataset,
    ensure_demo_target_descriptors,
)
from agentgate.demo.loan import LOAN_DATASET, LoanAgent
from agentgate.demo.targets import (
    build_demo_target_snapshot,
    get_demo_target_descriptor,
)
from agentgate.domain import EvaluationRun
from agentgate.integrations.job_dispatchers import JobDispatcher
from agentgate.integrations.job_dispatchers.celery import CeleryJobDispatcher
from agentgate.integrations.model_providers.environment import (
    load_judge_model_from_environment,
)
from agentgate.integrations.model_providers.openai_compatible import (
    OpenAICompatibleModelClient,
)
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
    evaluators: EvaluatorManagement
    targets: TargetCatalog
    runs: RunManagement
    results: ResultReader
    lineage: LineageQueries
    dispatcher: JobDispatcher
    demo_state: dict[str, dict]
    _judge_client: OpenAICompatibleModelClient | None = field(
        default=None,
        repr=False,
    )

    def close(self) -> None:
        """Release process-lifetime resources owned by these dependencies."""

        client = self._judge_client
        self._judge_client = None
        if client is not None:
            client.close()

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
        descriptor = get_demo_target_descriptor(version)
        resolved = self.targets.resolve_descriptor(
            descriptor.ref,
            descriptor.content_sha256,
        )
        return self.runs.create_run(
            build_demo_target_snapshot(resolved),
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
    target_catalog = TargetCatalog(repository)
    ensure_demo_target_descriptors(target_catalog)
    ensure_demo_dataset(repository)
    configured_judge = load_judge_model_from_environment()
    try:
        evaluator_management = (
            build_default_evaluator_management()
            if configured_judge is None
            else build_default_evaluator_management(
                judge_client=configured_judge.client,
                judge_model_id=configured_judge.model_id,
                judge_credential_ref=configured_judge.credential_ref,
            )
        )
        return ServerDependencies(
            repository=repository,
            datasets=DatasetManagement(repository),
            evaluators=evaluator_management,
            targets=target_catalog,
            runs=RunManagement(repository, evaluator_management),
            results=ResultReader(repository),
            lineage=LineageQueries(repository),
            dispatcher=dispatcher or CeleryJobDispatcher(),
            demo_state={},
            _judge_client=(
                configured_judge.client if configured_judge is not None else None
            ),
        )
    except Exception:
        if configured_judge is not None:
            configured_judge.client.close()
        raise
