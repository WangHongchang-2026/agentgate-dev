"""Write failed historical Cases into editable Dataset drafts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from agentgate.application.dataset_management import DatasetManagement
from agentgate.domain import Case, DatasetVersion, EvaluationResult, Outcome
from agentgate.storage.repository import AgentGateRepository


class HistoricalRunNotFound(LookupError):
    """Raised when the source Evaluation Run does not exist."""


class HistoricalCaseNotFound(LookupError):
    """Raised when the source Run did not execute the requested Case."""


class ResultCaseNotFailed(ValueError):
    """Raised when a Case without a failed Result is written back."""


class ResultCaseIdentityMismatch(ValueError):
    """Raised when an edited Case changes its historical identity."""


class HistoricalResultCase(BaseModel):
    """Exact Case snapshot and evaluator Results persisted for one Run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    dataset_id: str
    dataset_version: int
    case: Case
    results: tuple[EvaluationResult, ...]


class ResultCaseWritebackResult(BaseModel):
    """Dataset draft produced from one failed historical Case."""

    model_config = ConfigDict(frozen=True)

    source_run_id: str
    source_dataset_id: str
    source_dataset_version: int
    source_case_id: str
    draft: DatasetVersion


class ResultCaseWriteback:
    """Coordinate immutable Result reads with existing Dataset draft operations."""

    def __init__(
        self,
        repository: AgentGateRepository,
        datasets: DatasetManagement,
    ) -> None:
        self.repository = repository
        self.datasets = datasets

    def get_historical_case(
        self,
        run_id: str,
        case_id: str,
    ) -> HistoricalResultCase:
        run = self.repository.get_run(run_id)
        if run is None:
            raise HistoricalRunNotFound(f"unknown EvaluationRun: {run_id}")

        case = next(
            (item for item in run.manifest.execution_cases if item.id == case_id),
            None,
        )
        if case is None:
            raise HistoricalCaseNotFound(
                f"EvaluationRun did not execute Case: {run_id}/{case_id}"
            )

        results = tuple(
            result
            for result in self.repository.list_results(run.id)
            if result.case_id == case.id
        )
        dataset = run.manifest.dataset
        if dataset.version is None:
            raise ValueError("EvaluationRun manifest Dataset must be published")
        return HistoricalResultCase(
            run_id=run.id,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.version,
            case=case,
            results=results,
        )

    def write_to_draft(
        self,
        run_id: str,
        case_id: str,
        edited_case: Case,
    ) -> ResultCaseWritebackResult:
        source = self.get_historical_case(run_id, case_id)
        if not any(result.outcome is Outcome.FAIL for result in source.results):
            raise ResultCaseNotFailed(
                f"Case has no failed Result: {run_id}/{case_id}"
            )
        if edited_case.id != source.case.id:
            raise ResultCaseIdentityMismatch(
                "edited Case id must match the historical Case id"
            )

        dataset = self.datasets.get_dataset(source.dataset_id)
        if dataset.archived:
            raise ValueError("archived Dataset cannot be edited")
        draft = self.datasets.get_draft(dataset.id)
        if draft is None:
            latest = self.datasets.latest_published(dataset.id)
            draft = self.datasets.create_draft(
                dataset.id,
                based_on_version=latest.version,
            )
        draft = self.datasets.save_case(dataset.id, edited_case)
        return ResultCaseWritebackResult(
            source_run_id=source.run_id,
            source_dataset_id=source.dataset_id,
            source_dataset_version=source.dataset_version,
            source_case_id=source.case.id,
            draft=draft,
        )
