"""Local control-plane service shared by CLI, HTTP, and the Web UI."""

from __future__ import annotations

from agentgate.case import DatasetService
from agentgate.demo.loan import LOAN_DATASET, LOAN_DATASET_VERSION, LoanAgent
from agentgate.evaluator import EVALUATORS
from agentgate.run.core import RunEngine
from agentgate.storage.repository import AgentGateRepository


class EvaluationService:
    """Coordinate evaluation launches and read models for the local POC."""

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository
        self.engine = RunEngine(repository)
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
        latest = self.engine.report(completed[0].id) if completed else None
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
        return self.engine.report(run_id)

    def trace(self, run_id: str, case_id: str):
        return self.repository.get_trace(run_id, case_id)

    def versions(self) -> list[dict[str, str]]:
        return [
            {
                "id": version,
                "label": "风险版本" if version.endswith("risky") else "修复版本",
            }
            for version in LoanAgent.versions
        ]

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
                "implementation_id": item.implementation_id,
                "implementation_version": item.implementation_version,
                "config": item.config,
            }
            for item in EVALUATORS
        ]
