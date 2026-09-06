from __future__ import annotations

from typing import Protocol

from agentgate.domain import (
    Case, DatasetVersion, DatasetVersionStatus, ReleaseGateSpec, MetricPlan, EvaluationRun, RunManifest,
    RunStatus, TargetRef, TargetSnapshot, TargetType, Trace, content_sha256, transition_run,
)
from agentgate.evaluator import EVALUATORS, evaluate_case, validate_evaluation_plan
from agentgate.result.report import build_evaluation_report
from agentgate.storage.repository import AgentGateRepository


class Target(Protocol):
    def execute(self, run_id: str, case: Case, version: str) -> Trace: ...


class ExternalSchedulerAdapter(Protocol):
    def execute(self, target: Target, run_id: str, case: Case, version: str) -> Trace: ...


class LocalScheduler:
    def execute(self, target: Target, run_id: str, case: Case, version: str) -> Trace:
        return target.execute(run_id, case, version)


class PythonFunctionTarget:
    def __init__(self, function) -> None:
        self.function = function

    def execute(self, run_id: str, case: Case, version: str) -> Trace:
        return self.function(run_id, case, version)


class RunEngine:
    def __init__(
        self, repository: AgentGateRepository,
        scheduler: ExternalSchedulerAdapter | None = None,
    ) -> None:
        self.repository = repository
        self.scheduler = scheduler or LocalScheduler()

    def run(
        self, dataset: DatasetVersion, target: Target, target_version: str,
        provider: str = "deterministic", evaluators=EVALUATORS,
    ) -> EvaluationRun:
        if dataset.status != DatasetVersionStatus.PUBLISHED:
            raise ValueError("only published Dataset versions can be evaluated")
        selected = tuple(evaluators)
        validate_evaluation_plan(dataset, selected)
        manifest = RunManifest(
            dataset=dataset,
            target=TargetSnapshot(
                ref=TargetRef(
                    source_id="agentgate-demo",
                    target_type=TargetType.AGENT,
                    external_target_id="loan-agent",
                    external_version_id=target_version,
                ),
                display_name="loan-agent",
                adapter_type="python_function",
                adapter_version="1",
                descriptor_sha256=content_sha256({
                    "name": "loan-agent",
                    "version": target_version,
                    "provider": provider,
                }),
                invocation_config={"provider": provider},
            ),
            evaluator_specs=selected,
            primary_evaluator_ids=tuple(item.id for item in selected),
            metric_plan=MetricPlan(),
            gate_spec=ReleaseGateSpec(),
        )
        run = transition_run(EvaluationRun(manifest=manifest), RunStatus.RUNNING)
        self.repository.save_run(run)
        results = []
        try:
            for case in dataset.cases:
                trace = self.scheduler.execute(target, run.id, case, target_version)
                self.repository.save_trace(trace)
                results.extend(evaluate_case(case, trace, manifest.evaluator_specs))
            self.repository.save_results(results)
            completed = transition_run(run, RunStatus.COMPLETED)
            self.repository.save_run(completed)
            return completed
        except Exception as exc:
            failed = transition_run(
                run, RunStatus.FAILED, error=str(exc) or type(exc).__name__
            )
            self.repository.save_run(failed)
            raise

    def report(self, run_id: str):
        run = self.repository.get_run(run_id)
        if run is None or run.status != RunStatus.COMPLETED:
            return None
        return build_evaluation_report(run, self.repository.list_results(run_id))
