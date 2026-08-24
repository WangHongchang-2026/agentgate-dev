"""Application commands for Run creation and rerun workflows."""

from __future__ import annotations

from agentgate.application.target_catalog import TargetCatalog
from agentgate.demo.loan import LoanAgent
from agentgate.domain import Run
from agentgate.run.core import RunEngine
from agentgate.storage.base import AgentGateRepository


class RunManagement:
    def __init__(
        self,
        repository: AgentGateRepository,
        engine: RunEngine,
        target_catalog: TargetCatalog,
    ) -> None:
        self.repository = repository
        self.engine = engine
        self.target_catalog = target_catalog

    def latest_target_version(self) -> str:
        return self.target_catalog.resolve(None)

    def rerun_case(
        self,
        source_run_id: str,
        case_id: str,
        target_version: str | None = None,
    ) -> Run:
        source = self.repository.get_run(source_run_id)
        if source is None:
            raise LookupError("run not found")
        if source.status != "completed":
            raise ValueError("only completed Runs can be rerun")
        case = next(
            (item for item in source.snapshot.dataset.cases if item.id == case_id), None
        )
        if case is None:
            raise LookupError("case not found in source Run snapshot")
        version = self.target_catalog.resolve(target_version)
        target_snapshot = source.snapshot.target.model_copy(update={"version": version})
        return self.engine.run(
            source.snapshot.dataset,
            LoanAgent(self.repository),
            version,
            evaluators=source.snapshot.evaluator_specs,
            target_snapshot=target_snapshot,
            metric_plan=source.snapshot.metric_plan,
            gate_spec=source.snapshot.gate_spec,
            selected_case_ids=(case.id,),
            parent_run_id=source.id,
            root_run_id=source.root_run_id or source.id,
            rerun_case_id=case.id,
        )
