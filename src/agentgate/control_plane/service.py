"""Local control-plane service shared by CLI, HTTP, and the Web UI."""

from __future__ import annotations

from agentgate.application import ResultReader, RunManagement, TargetCatalog
from agentgate.case import DatasetService
from agentgate.demo.loan import LOAN_DATASET, LOAN_DATASET_VERSION, LoanAgent
from agentgate.evaluator import EVALUATORS
from agentgate.run.core import RunEngine
from agentgate.storage.base import AgentGateRepository


class EvaluationService:
    """Coordinate evaluation launches and read models for the local POC."""

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository
        self.engine = RunEngine(repository)
        self.target_catalog = TargetCatalog()
        self.run_management = RunManagement(
            repository, self.engine, self.target_catalog
        )
        self.result_reader = ResultReader(repository, self.engine)
        self.dataset_service = DatasetService(repository)
        self.dataset_service.seed(LOAN_DATASET, LOAN_DATASET_VERSION)

    def launch(
        self, version: str, dataset_id: str | None = None,
        dataset_version: int | None = None, evaluator_ids: list[str] | None = None,
    ):
        dataset_id = dataset_id or LOAN_DATASET.id
        dataset = (
            self.dataset_service.get_version(dataset_id, dataset_version)
            if dataset_version is not None
            else self.dataset_service.latest_published(dataset_id)
        )
        selected = EVALUATORS if evaluator_ids is None else tuple(
            item for item in EVALUATORS if item.id in evaluator_ids
        )
        if not selected:
            raise ValueError("at least one evaluator is required")
        unknown = set(evaluator_ids or ()) - {item.id for item in EVALUATORS}
        if unknown:
            raise ValueError(f"unknown evaluators: {', '.join(sorted(unknown))}")
        return self.engine.run(
            dataset, LoanAgent(self.repository), version, evaluators=selected
        )

    def overview(self) -> dict:
        runs = self.repository.list_runs()
        completed = [run for run in runs if run.status == "completed"]
        latest = self.engine.report(runs[0].id) if runs else None
        case_count = sum(
            len(version.cases)
            for dataset in self.dataset_service.list_datasets()
            if (version := self.repository.get_latest_dataset_version(dataset.id)) is not None
        )
        return {
            "total_runs": len(runs),
            "completed_runs": len(completed),
            "case_count": case_count,
            "latest": latest,
        }

    def run_detail(self, run_id: str):
        return self.result_reader.run_detail(run_id)

    def rerun_case(
        self, run_id: str, case_id: str, target_version: str | None = None,
    ):
        return self.run_management.rerun_case(run_id, case_id, target_version)

    def rerun_comparison(self, rerun_run_id: str) -> dict:
        return self.result_reader.rerun_comparison(rerun_run_id)

    def latest_target_version(self) -> str:
        return self.run_management.latest_target_version()

    def trace(self, run_id: str, case_id: str):
        return self.result_reader.trace(run_id, case_id)

    def versions(self) -> list[dict]:
        return list(self.target_catalog.versions())

    def datasets(self) -> list[dict]:
        summaries = []
        for dataset in self.dataset_service.list_datasets():
            latest = self.repository.get_latest_dataset_version(dataset.id)
            draft = self.repository.get_dataset_draft(dataset.id)
            summaries.append({
                **dataset.model_dump(mode="json"),
                "version": latest.version if latest else None,
                "case_count": len(latest.cases) if latest else 0,
                "has_draft": draft is not None,
            })
        return summaries

    def evaluators(self) -> list[dict]:
        return [
            {
                "id": item.id,
                "name": item.name,
                "kind": item.kind,
                "version": item.version,
                "dimension": item.dimension,
                "metric": item.metric,
                "severity": item.severity,
                "evaluator_type": item.evaluator_type,
                "operator": getattr(item, "operator", None),
            }
            for item in EVALUATORS
        ]
