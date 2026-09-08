"""Evaluation Run submission, activity, and status endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from agentgate.application import RunActivity, RunProgress
from agentgate.domain import EvaluationRun, RunStatus
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import (
    raise_not_found,
    raise_service_unavailable,
    raise_unprocessable,
)


router = APIRouter(prefix="/api", tags=["runs"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


class LaunchRequest(BaseModel):
    version: str
    dataset_id: str
    dataset_version: int = Field(ge=1)
    evaluator_ids: list[str] | None = None
    max_parallel_cases: int = Field(default=1, ge=1, le=32)


@router.get("/runs")
def list_runs(
    dependencies: Dependencies,
    status: RunStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[EvaluationRun]:
    return dependencies.results.list_runs(limit=limit, status=status)


@router.get("/runs/activity")
def run_activity(
    dependencies: Dependencies,
    recent_limit: int = Query(default=20, ge=1, le=100),
) -> RunActivity:
    dependencies.runs.fail_stale_runs()
    return dependencies.results.activity(recent_limit=recent_limit)


@router.post("/evaluations", status_code=202)
def launch_evaluation(
    request: LaunchRequest, dependencies: Dependencies
) -> RunProgress:
    try:
        run = dependencies.submit_demo_run(
            request.version,
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            evaluator_ids=request.evaluator_ids,
            max_parallel_cases=request.max_parallel_cases,
        )
        return dependencies.results.get_run_progress(run.id)
    except RuntimeError as error:
        raise_service_unavailable(error)
    except ValueError as error:
        raise_unprocessable(error)


@router.get("/runs/{run_id}/status")
def run_status(run_id: str, dependencies: Dependencies) -> RunProgress:
    try:
        dependencies.runs.fail_stale_runs()
        return dependencies.results.get_run_progress(run_id)
    except LookupError as error:
        raise_not_found(error)
