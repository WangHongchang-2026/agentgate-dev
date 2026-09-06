"""Read-only application workflows for Runs, Results, Traces, and overview data."""

from __future__ import annotations

from typing import Any

from agentgate.domain import EvaluationReport, EvaluationRun, RunStatus, Trace
from agentgate.result.report import build_evaluation_report
from agentgate.storage.repository import AgentGateRepository


class ResultReader:
    """Load persisted evaluation outputs without owning their calculations."""

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository

    def list_runs(self, limit: int = 50) -> list[EvaluationRun]:
        return self.repository.list_runs(limit=limit)

    def get_report(self, run_id: str) -> EvaluationReport:
        run = self._get_run(run_id)
        if run.status is not RunStatus.COMPLETED:
            raise ValueError("EvaluationReport requires a completed EvaluationRun")
        return build_evaluation_report(run, self.repository.list_results(run.id))

    def get_trace(self, run_id: str, case_id: str) -> Trace:
        self._get_run(run_id)
        trace = self.repository.get_trace(run_id, case_id)
        if trace is None:
            raise LookupError(f"unknown Trace: {run_id}/{case_id}")
        return trace

    def overview(self) -> dict[str, Any]:
        runs = self.repository.list_runs()
        statuses = {
            status: sum(run.status is status for run in runs)
            for status in RunStatus
        }
        datasets = self.repository.list_datasets()
        case_count = 0
        for dataset in datasets:
            version = self.repository.get_latest_published_dataset_version(dataset.id)
            if version is not None:
                case_count += len(version.cases)
        latest_run = next(
            (run for run in runs if run.status is RunStatus.COMPLETED), None
        )
        latest = self.get_report(latest_run.id) if latest_run is not None else None
        return {
            "total_runs": len(runs),
            "pending_runs": statuses[RunStatus.PENDING],
            "running_runs": statuses[RunStatus.RUNNING],
            "completed_runs": statuses[RunStatus.COMPLETED],
            "failed_runs": statuses[RunStatus.FAILED],
            "cancelled_runs": statuses[RunStatus.CANCELLED],
            "dataset_count": len(datasets),
            "case_count": case_count,
            "latest": latest,
        }

    def _get_run(self, run_id: str) -> EvaluationRun:
        run = self.repository.get_run(run_id)
        if run is None:
            raise LookupError(f"unknown EvaluationRun: {run_id}")
        return run
