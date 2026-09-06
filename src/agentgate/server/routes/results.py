"""Evaluation overview, report, and Trace read endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from agentgate.domain import EvaluationReport, Trace
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_conflict, raise_not_found


router = APIRouter(prefix="/api", tags=["results"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


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


@router.get("/runs/{run_id}/traces/{case_id}")
def trace_detail(
    run_id: str, case_id: str, dependencies: Dependencies
) -> Trace:
    try:
        return dependencies.results.get_trace(run_id, case_id)
    except LookupError as error:
        raise_not_found(error)
