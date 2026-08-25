"""Local control-plane service shared by CLI, HTTP, and the Web UI."""

from __future__ import annotations

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
        return self.engine.report(run_id)

    def rerun_case(
        self, run_id: str, case_id: str, target_version: str | None = None,
    ):
        source = self.repository.get_run(run_id)
        if source is None:
            raise LookupError("run not found")
        if source.status != "completed":
            raise ValueError("only completed Runs can be rerun")
        case = next(
            (item for item in source.snapshot.dataset.cases if item.id == case_id), None
        )
        if case is None:
            raise LookupError("case not found in source Run snapshot")
        version = target_version or self.latest_target_version()
        if version not in LoanAgent.versions:
            raise ValueError(f"unknown target version: {version}")
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

    @staticmethod
    def latest_target_version() -> str:
        return LoanAgent.versions[-1]

    def rerun_comparison(self, rerun_run_id: str) -> dict:
        rerun = self.repository.get_run(rerun_run_id)
        if rerun is None:
            raise LookupError("run not found")
        if rerun.parent_run_id is None or rerun.rerun_case_id is None:
            raise ValueError("run is not a single-Case rerun")
        parent = self.repository.get_run(rerun.parent_run_id)
        if parent is None:
            raise LookupError("parent run not found")
        if rerun.status != "completed":
            raise ValueError("rerun is not completed")
        case_id = rerun.rerun_case_id
        case = next(item for item in rerun.snapshot.dataset.cases if item.id == case_id)
        original = {
            item.evaluator_id: item
            for item in self.repository.list_results(parent.id)
            if item.case_id == case_id
        }
        current = {
            item.evaluator_id: item
            for item in self.repository.list_results(rerun.id)
            if item.case_id == case_id
        }
        comparisons = []
        for evaluator_id in sorted(set(original) | set(current)):
            before, after = original.get(evaluator_id), current.get(evaluator_id)
            status = _comparison_status(before, after)
            comparisons.append({
                "evaluator_id": evaluator_id,
                "evaluator_name": (after or before).evaluator_name,
                "status": status,
                "before": _result_summary(before),
                "after": _result_summary(after),
            })
        counts = {
            status: sum(item["status"] == status for item in comparisons)
            for status in ("improved", "regressed", "unchanged", "incomparable")
        }
        overall = _overall_comparison(counts, len(comparisons))
        return {
            "root_run_id": rerun.root_run_id,
            "parent_run_id": parent.id,
            "rerun_run_id": rerun.id,
            "case_id": case_id,
            "case_name": case.name,
            "before_target_version": parent.snapshot.target.version,
            "after_target_version": rerun.snapshot.target.version,
            "overall": overall,
            "counts": counts,
            "evaluators": comparisons,
        }

    def trace(self, run_id: str, case_id: str):
        return self.repository.get_trace(run_id, case_id)

    def versions(self) -> list[dict[str, str]]:
        return [
            {
                "id": version,
                "label": "风险版本" if version.endswith("risky") else "修复版本",
                "is_latest": version == self.latest_target_version(),
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
                "evaluator_type": item.evaluator_type,
                "operator": getattr(item, "operator", None),
            }
            for item in EVALUATORS
        ]


def _result_summary(result) -> dict | None:
    if result is None:
        return None
    return {
        "outcome": result.outcome,
        "score": result.score,
        "reason": result.reason,
    }


def _comparison_status(before, after) -> str:
    if before is None or after is None:
        return "incomparable"
    excluded = {"error", "not_applicable"}
    if before.outcome in excluded or after.outcome in excluded:
        return "incomparable"
    if before.outcome == after.outcome and before.score == after.score:
        return "unchanged"
    if before.outcome in {"fail", "review"} and after.outcome == "pass":
        return "improved"
    if before.outcome == "pass" and after.outcome in {"fail", "review"}:
        return "regressed"
    if before.score is not None and after.score is not None:
        if after.score > before.score:
            return "improved"
        if after.score < before.score:
            return "regressed"
    return "unchanged"


def _overall_comparison(counts: dict[str, int], total: int) -> str:
    if counts["improved"] and counts["regressed"]:
        return "mixed"
    if counts["regressed"]:
        return "regressed"
    if counts["improved"]:
        return "improved"
    if total and counts["unchanged"] == total:
        return "unchanged"
    return "incomparable"
