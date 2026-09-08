"""Application workflows for creating and executing Evaluation Runs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from agentgate.domain import (
    EvaluationRun,
    EvaluatorRef,
    MetricPlan,
    ReleaseGateSpec,
    RunManifest,
    RunStatus,
    TargetSnapshot,
    normalize_utc,
    transition_run,
    utcnow,
)
from agentgate.integrations.job_dispatchers import JobDispatcher
from agentgate.run.engine import RunEngine, TraceResolver
from agentgate.run.retry import retry_delay_seconds
from agentgate.run.target_protocol import TargetAdapterProtocol
from agentgate.storage.repository import AgentGateRepository

from .dataset_management import DatasetManagement
from .evaluator_management import EvaluatorManagement
from .target_catalog import TargetCatalog


class RunManagement:
    """Coordinate immutable Run creation and worker-side execution."""

    def __init__(
        self,
        repository: AgentGateRepository,
        evaluator_management: EvaluatorManagement,
    ) -> None:
        self.repository = repository
        self.dataset_management = DatasetManagement(repository)
        self.evaluator_management = evaluator_management
        self.target_catalog = TargetCatalog(repository)

    def create_run(
        self,
        target: TargetSnapshot,
        *,
        dataset_id: str,
        dataset_version: int | None = None,
        case_ids: Sequence[str] | None = None,
        evaluator_ids: Sequence[str] | None = None,
        evaluator_refs: Sequence[EvaluatorRef] | None = None,
        metric_plan: MetricPlan | None = None,
        gate_spec: ReleaseGateSpec | None = None,
        timeout_seconds: float = 300,
        max_parallel_cases: int = 1,
        max_retries: int = 0,
    ) -> EvaluationRun:
        """Resolve exact inputs, persist a pending Run, and return it."""

        self.target_catalog.resolve_descriptor(
            target.ref,
            target.descriptor_sha256,
        )
        dataset = (
            self.dataset_management.get_version(dataset_id, dataset_version)
            if dataset_version is not None
            else self.dataset_management.latest_published(dataset_id)
        )
        if evaluator_ids is not None and evaluator_refs is not None:
            raise ValueError("use evaluator_ids or evaluator_refs, not both")
        selected = (
            self.evaluator_management.select_versions(evaluator_refs)
            if evaluator_refs is not None
            else self.evaluator_management.select(evaluator_ids)
        )
        self.evaluator_management.validate_plan(dataset, selected)
        run = EvaluationRun(
            manifest=RunManifest(
                dataset=dataset,
                selected_case_ids=tuple(case_ids) if case_ids is not None else None,
                target=target,
                evaluator_specs=selected,
                primary_evaluator_ids=tuple(spec.id for spec in selected),
                metric_plan=metric_plan or MetricPlan(),
                gate_spec=gate_spec or ReleaseGateSpec(),
                timeout_seconds=timeout_seconds,
                max_parallel_cases=max_parallel_cases,
                max_retries=max_retries,
            )
        )
        self.repository.save_run(run)
        return run

    def execute_run(
        self,
        run_id: str,
        target_adapter: TargetAdapterProtocol,
        trace_resolver: TraceResolver,
    ) -> EvaluationRun:
        """Execute one previously created pending Run through the shared Engine."""

        run = self.repository.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown EvaluationRun: {run_id}")
        if run.status is not RunStatus.PENDING:
            return run
        engine = RunEngine(
            self.repository,
            self.evaluator_management.evaluate_case,
            trace_resolver,
        )
        return engine.execute(run, target_adapter)

    def dispatch_run(
        self, run_id: str, dispatcher: JobDispatcher
    ) -> EvaluationRun:
        """Submit one persisted pending Run for worker-side execution."""

        run = self.repository.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown EvaluationRun: {run_id}")
        if run.status is not RunStatus.PENDING:
            raise ValueError("only a pending EvaluationRun can be dispatched")
        try:
            dispatcher.submit(run.id)
        except Exception as exc:
            failed = transition_run(
                run,
                RunStatus.FAILED,
                error=f"Run dispatch failed: {type(exc).__name__}",
            )
            try:
                self.repository.save_run(failed)
            except ValueError:
                current = self.repository.get_run(run.id)
                if current is None or current.status is RunStatus.PENDING:
                    raise
            raise RuntimeError("Run dispatch failed") from exc
        return run

    def fail_stale_runs(
        self,
        *,
        now: datetime | None = None,
        grace_seconds: float = 30,
    ) -> list[EvaluationRun]:
        """Fail running Runs whose execution recovery deadline has expired."""

        if grace_seconds < 0:
            raise ValueError("grace_seconds must not be negative")
        current_time = normalize_utc(now or utcnow(), "stale Run check time")
        failed_runs: list[EvaluationRun] = []
        for run in self.repository.list_runs_by_status(RunStatus.RUNNING):
            case_count = len(run.manifest.execution_cases)
            batch_count = (
                case_count + run.manifest.max_parallel_cases - 1
            ) // run.manifest.max_parallel_cases
            retry_delay_budget = sum(
                retry_delay_seconds(retry_number)
                for retry_number in range(1, run.manifest.max_retries + 1)
            )
            execution_seconds = (
                run.manifest.timeout_seconds * batch_count
                + case_count
                * (
                    run.manifest.timeout_seconds * run.manifest.max_retries
                    + retry_delay_budget
                )
            )
            deadline = run.started_at + timedelta(
                seconds=execution_seconds + grace_seconds
            )
            if deadline > current_time:
                continue
            failed = transition_run(
                run,
                RunStatus.FAILED,
                occurred_at=current_time,
                error="Execution worker exceeded its recovery deadline",
            )
            try:
                self.repository.save_run(failed)
            except ValueError:
                current = self.repository.get_run(run.id)
                if current is None or current.status is RunStatus.RUNNING:
                    raise
                continue
            failed_runs.append(failed)
        return failed_runs
