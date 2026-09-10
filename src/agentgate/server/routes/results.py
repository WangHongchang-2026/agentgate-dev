"""Evaluation overview, report, and Trace read endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agentgate.application.result_case_writeback import (
    HistoricalCaseNotFound,
    HistoricalResultCase,
    HistoricalRunNotFound,
    ResultCaseIdentityMismatch,
    ResultCaseNotFailed,
    ResultCaseWritebackResult,
)
from agentgate.domain import Case, EvaluationReport, Trace
from agentgate.result.analytics import ResultAnalytics
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import (
    raise_conflict,
    raise_not_found,
    raise_unprocessable,
)


router = APIRouter(prefix="/api", tags=["results"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


class WritebackResultCaseRequest(BaseModel):
    case: Case


@router.get("/overview")
def overview(dependencies: Dependencies) -> dict[str, Any]:
    return dependencies.results.overview()


@router.get("/runs/{run_id}")
def run_report(run_id: str, dependencies: Dependencies) -> EvaluationReport:
    try:
        return dependencies.results.get_report(run_id)
    except LookupError as error:
        raise_not_found(error)
    except ValueError as error:
        raise_conflict(error)


@router.get("/runs/{run_id}/analytics")
def result_analytics(
    run_id: str,
    dependencies: Dependencies,
) -> ResultAnalytics:
    try:
        return dependencies.results.get_analytics(run_id)
    except LookupError as error:
        raise_not_found(error)
    except ValueError as error:
        raise_conflict(error)


@router.get("/runs/{run_id}/traces/{case_id}")
def trace_detail(
    run_id: str, case_id: str, dependencies: Dependencies
) -> Trace:
    try:
        return dependencies.results.get_trace(run_id, case_id)
    except LookupError as error:
        raise_not_found(error)


@router.get("/runs/{run_id}/cases/{case_id}")
def historical_case_detail(
    run_id: str,
    case_id: str,
    dependencies: Dependencies,
) -> HistoricalResultCase:
    try:
        return dependencies.result_case_writeback.get_historical_case(
            run_id,
            case_id,
        )
    except (HistoricalRunNotFound, HistoricalCaseNotFound) as error:
        raise_not_found(error)


@router.post("/runs/{run_id}/cases/{case_id}/writeback")
def writeback_result_case(
    run_id: str,
    case_id: str,
    request: WritebackResultCaseRequest,
    dependencies: Dependencies,
) -> ResultCaseWritebackResult:
    try:
        return dependencies.result_case_writeback.write_to_draft(
            run_id,
            case_id,
            request.case,
        )
    except (HistoricalRunNotFound, HistoricalCaseNotFound) as error:
        raise_not_found(error)
    except ResultCaseNotFailed as error:
        raise_conflict(error)
    except ResultCaseIdentityMismatch as error:
        raise_unprocessable(error)
    except ValueError as error:
        raise_conflict(error)
