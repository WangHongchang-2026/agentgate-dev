"""Process-lifetime dependencies used by AgentGate HTTP routes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import Request

from agentgate.application import (
    ABRunPair,
    DatasetManagement,
    LineageQueries,
    OptimizationAnalysis,
    ResultReader,
    RunManagement,
    SkillAnalysis,
    TargetCatalog,
    create_ab_runs,
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
from agentgate.domain import (
    EvaluationRun,
    EvaluatorRef,
    SkillAnalysisReport,
    TargetSnapshot,
)
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
from agentgate.skill_analysis import analyze_skill_relationships
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
    skill_analysis: SkillAnalysis
    optimization: OptimizationAnalysis
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

    def analyze_demo_target(self, version: str) -> SkillAnalysisReport:
        """Analyze the exact demo Target selected during Run configuration."""

        target = self._resolve_demo_target(version)
        return self.skill_analysis.analyze_target(target.descriptor_sha256)

    def submit_demo_run(
        self,
        version: str,
        *,
        dataset_id: str = LOAN_DATASET.id,
        dataset_version: int | None = None,
        case_ids: list[str] | None = None,
        evaluator_ids: list[str] | None = None,
        timeout_seconds: float = 300,
        max_parallel_cases: int = 1,
    ) -> EvaluationRun:
        """Create and asynchronously dispatch one POC Loan Agent evaluation."""

        run = self._create_demo_run(
            version,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            case_ids=case_ids,
            evaluator_ids=evaluator_ids,
            timeout_seconds=timeout_seconds,
            max_parallel_cases=max_parallel_cases,
        )
        return self.runs.dispatch_run(run.id, self.dispatcher)

    def submit_ab_runs(
        self,
        baseline_version: str,
        candidate_version: str,
        *,
        dataset_id: str = LOAN_DATASET.id,
        dataset_version: int | None = None,
        evaluator_refs: list[EvaluatorRef] | None = None,
    ) -> ABRunPair:
        """Create and dispatch one controlled pair of POC Loan Agent Runs."""

        return create_ab_runs(
            self.runs,
            self.dispatcher,
            self._resolve_demo_target(baseline_version),
            self._resolve_demo_target(candidate_version),
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            evaluator_refs=evaluator_refs,
        )

    def execute_demo_run(
        self,
        version: str,
        *,
        dataset_id: str = LOAN_DATASET.id,
        dataset_version: int | None = None,
        case_ids: list[str] | None = None,
        evaluator_ids: list[str] | None = None,
    ) -> EvaluationRun:
        """Create and synchronously execute one POC Loan Agent evaluation."""

        run = self._create_demo_run(
            version,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            case_ids=case_ids,
            evaluator_ids=evaluator_ids,
            timeout_seconds=300,
            max_parallel_cases=1,
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
        case_ids: list[str] | None,
        evaluator_ids: list[str] | None,
        timeout_seconds: float,
        max_parallel_cases: int,
    ) -> EvaluationRun:
        target = self._resolve_demo_target(version)
        return self.runs.create_run(
            target,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            case_ids=case_ids,
            evaluator_ids=evaluator_ids,
            timeout_seconds=timeout_seconds,
            max_parallel_cases=max_parallel_cases,
        )

    def _resolve_demo_target(self, version: str) -> TargetSnapshot:
        if version not in LoanAgent.versions:
            raise ValueError(f"unknown demo Target version: {version}")
        descriptor = get_demo_target_descriptor(version)
        resolved = self.targets.resolve_descriptor(
            descriptor.ref,
            descriptor.content_sha256,
        )
        return build_demo_target_snapshot(resolved)


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
            build_default_evaluator_management(repository)
            if configured_judge is None
            else build_default_evaluator_management(
                repository,
                judge_client=configured_judge.client,
                judge_model_id=configured_judge.model_id,
                judge_credential_ref=configured_judge.credential_ref,
            )
        )
        skill_analyzer = (
            None
            if configured_judge is None
            else partial(
                analyze_skill_relationships,
                model_client=configured_judge.client,
                model_id=configured_judge.model_id,
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
            skill_analysis=SkillAnalysis(repository, skill_analyzer),
            optimization=OptimizationAnalysis(repository),
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
