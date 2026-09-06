"""Application workflows for creating and executing Evaluation Runs."""

from __future__ import annotations

from collections.abc import Sequence

from agentgate.domain import (
    EvaluationRun,
    EvaluatorSpec,
    MetricPlan,
    ReleaseGateSpec,
    RunManifest,
    TargetSnapshot,
)
from agentgate.evaluator import evaluate_case, validate_evaluation_plan
from agentgate.run.engine import RunEngine, TraceResolver
from agentgate.run.target_protocol import TargetAdapterProtocol
from agentgate.storage.repository import AgentGateRepository

from .dataset_management import DatasetManagement


class RunManagement:
    """Coordinate immutable Run creation and worker-side execution."""

    def __init__(
        self,
        repository: AgentGateRepository,
        evaluator_specs: Sequence[EvaluatorSpec],
    ) -> None:
        self.repository = repository
        self.dataset_management = DatasetManagement(repository)
        self.evaluator_specs = tuple(evaluator_specs)
        if not self.evaluator_specs:
            raise ValueError("at least one available Evaluator is required")
        ids = tuple(spec.id for spec in self.evaluator_specs)
        if len(set(ids)) != len(ids):
            raise ValueError("available Evaluator IDs must be unique")

    def create_run(
        self,
        target: TargetSnapshot,
        *,
        dataset_id: str,
        dataset_version: int | None = None,
        evaluator_ids: Sequence[str] | None = None,
        metric_plan: MetricPlan | None = None,
        gate_spec: ReleaseGateSpec | None = None,
        timeout_seconds: float = 300,
    ) -> EvaluationRun:
        """Resolve exact inputs, persist a pending Run, and return it."""

        dataset = (
            self.dataset_management.get_version(dataset_id, dataset_version)
            if dataset_version is not None
            else self.dataset_management.latest_published(dataset_id)
        )
        selected = self._select_evaluators(evaluator_ids)
        validate_evaluation_plan(dataset, selected)
        run = EvaluationRun(
            manifest=RunManifest(
                dataset=dataset,
                target=target,
                evaluator_specs=selected,
                primary_evaluator_ids=tuple(spec.id for spec in selected),
                metric_plan=metric_plan or MetricPlan(),
                gate_spec=gate_spec or ReleaseGateSpec(),
                timeout_seconds=timeout_seconds,
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
        engine = RunEngine(self.repository, evaluate_case, trace_resolver)
        return engine.execute(run, target_adapter)

    def _select_evaluators(
        self, evaluator_ids: Sequence[str] | None
    ) -> tuple[EvaluatorSpec, ...]:
        if evaluator_ids is None:
            return self.evaluator_specs
        requested = tuple(evaluator_ids)
        if not requested:
            raise ValueError("at least one Evaluator is required")
        if len(set(requested)) != len(requested):
            raise ValueError("evaluator_ids must be unique")
        by_id = {spec.id: spec for spec in self.evaluator_specs}
        unknown = set(requested).difference(by_id)
        if unknown:
            raise ValueError(f"unknown Evaluators: {', '.join(sorted(unknown))}")
        return tuple(by_id[evaluator_id] for evaluator_id in requested)
