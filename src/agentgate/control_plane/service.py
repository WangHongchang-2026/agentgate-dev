"""Local control-plane service shared by CLI, HTTP, and the Web UI."""

from __future__ import annotations

from agentgate.application import (
    DatasetManagement,
    ResultReader,
    RunManagement,
    TargetCatalog,
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
from agentgate.evaluator import EVALUATORS
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.storage.repository import AgentGateRepository


class EvaluationService:
    """Coordinate evaluation launches and read models for the local POC."""

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository
        self.loan_state: dict[str, dict] = {}
        self.dataset_management = DatasetManagement(repository)
        self.run_management = RunManagement(repository, EVALUATORS)
        self.result_reader = ResultReader(repository)
        self.target_catalog = TargetCatalog(repository)
        ensure_demo_target_descriptors(self.target_catalog)
        ensure_demo_dataset(repository)

    def launch(
        self, version: str, dataset_id: str | None = None,
        dataset_version: int | None = None, evaluator_ids: list[str] | None = None,
    ):
        descriptor = get_demo_target_descriptor(version)
        target = build_demo_target_snapshot(
            self.target_catalog.resolve_descriptor(
                descriptor.ref,
                descriptor.content_sha256,
            )
        )
        run = self.run_management.create_run(
            target,
            dataset_id=dataset_id or LOAN_DATASET.id,
            dataset_version=dataset_version,
            evaluator_ids=evaluator_ids,
        )
        capture = InMemoryTraceCapture()
        try:
            adapter = DemoLoanTargetAdapter(
                capture, state_store=self.loan_state
            )
            return self.run_management.execute_run(run.id, adapter, capture.resolve)
        finally:
            capture.shutdown()

    def overview(self) -> dict:
        return self.result_reader.overview()

    def run_detail(self, run_id: str):
        try:
            return self.result_reader.get_report(run_id)
        except (LookupError, ValueError):
            return None

    def trace(self, run_id: str, case_id: str):
        try:
            return self.result_reader.get_trace(run_id, case_id)
        except LookupError:
            return None

    def versions(self) -> list[dict[str, str]]:
        return [
            {
                "id": version,
                "label": "Risky version" if version.endswith("risky") else "Fixed version",
            }
            for version in LoanAgent.versions
        ]

    def datasets(self) -> list[dict]:
        summaries = []
        for dataset in self.dataset_management.list_datasets():
            latest = self.repository.get_latest_published_dataset_version(dataset.id)
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
