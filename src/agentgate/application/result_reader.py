"""Read-only application workflows for reports, traces, and comparisons."""

from __future__ import annotations

from agentgate.result.comparison import compare_case_results
from agentgate.run.core import RunEngine
from agentgate.storage.base import AgentGateRepository


class ResultReader:
    def __init__(self, repository: AgentGateRepository, engine: RunEngine) -> None:
        self.repository = repository
        self.engine = engine

    def run_detail(self, run_id: str):
        return self.engine.report(run_id)

    def trace(self, run_id: str, case_id: str):
        return self.repository.get_trace(run_id, case_id)

    def rerun_comparison(self, rerun_run_id: str) -> dict:
        rerun = self.repository.get_run(rerun_run_id)
        if rerun is None:
            raise LookupError("run not found")
        if rerun.parent_run_id is None or rerun.rerun_case_id is None:
            raise ValueError("run is not a single-Case rerun")
        if rerun.status != "completed":
            raise ValueError("rerun is not completed")
        parent = self.repository.get_run(rerun.parent_run_id)
        if parent is None:
            raise LookupError("parent run not found")
        case_id = rerun.rerun_case_id
        case = next(
            (item for item in rerun.snapshot.dataset.cases if item.id == case_id), None
        )
        if case is None:
            raise ValueError("rerun Case is missing from its snapshot")
        original = (
            item for item in self.repository.list_results(parent.id)
            if item.case_id == case_id
        )
        current = (
            item for item in self.repository.list_results(rerun.id)
            if item.case_id == case_id
        )
        comparison = compare_case_results(original, current)
        return {
            "root_run_id": rerun.root_run_id,
            "parent_run_id": parent.id,
            "rerun_run_id": rerun.id,
            "case_id": case_id,
            "case_name": case.name,
            "before_target_version": parent.snapshot.target.version,
            "after_target_version": rerun.snapshot.target.version,
            **comparison,
        }
