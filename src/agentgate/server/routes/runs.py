"""Evaluation Run submission, activity, and status endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agentgate.application import RunActivity, RunProgress
from agentgate.application.skill_analysis import SkillAnalysisUnavailable
from agentgate.domain import (
    EvaluationRun,
    RunManifest,
    RunStatus,
    SkillAnalysisReport,
)
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import (
    raise_conflict,
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
    timeout_seconds: float = Field(default=300, gt=0, le=3600)
    max_parallel_cases: int = Field(default=1, ge=1, le=32)
    max_retries: int = Field(default=0, ge=0, le=5)
    case_ids: list[str] | None = None


class RunSetupSkillAnalysisRequest(BaseModel):
    version: str


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
            case_ids=request.case_ids,
            evaluator_ids=request.evaluator_ids,
            timeout_seconds=request.timeout_seconds,
            max_parallel_cases=request.max_parallel_cases,
            max_retries=request.max_retries,
        )
        return dependencies.results.get_run_progress(run.id)
    except RuntimeError as error:
        raise_service_unavailable(error)
    except ValueError as error:
        raise_unprocessable(error)


@router.post("/evaluations/skill-analysis", status_code=201)
def analyze_evaluation_target(
    request: RunSetupSkillAnalysisRequest,
    dependencies: Dependencies,
) -> SkillAnalysisReport:
    try:
        return dependencies.analyze_demo_target(request.version)
    except SkillAnalysisUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail="Skill analysis is unavailable",
        ) from error
    except ValueError as error:
        raise_unprocessable(error)


@router.get("/runs/{run_id}/status")
def run_status(run_id: str, dependencies: Dependencies) -> RunProgress:
    try:
        dependencies.runs.fail_stale_runs()
        return dependencies.results.get_run_progress(run_id)
    except LookupError as error:
        raise_not_found(error)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, dependencies: Dependencies) -> RunProgress:
    try:
        cancelled = dependencies.runs.cancel_run(
            run_id,
            dependencies.dispatcher,
        )
        return dependencies.results.get_run_progress(cancelled.id)
    except LookupError as error:
        raise_not_found(error)
    except ValueError as error:
        raise_conflict(error)


@router.get("/runs/{run_id}/manifest")
def run_manifest(run_id: str, dependencies: Dependencies) -> RunManifest:
    try:
        return dependencies.results.get_run_manifest(run_id)
    except LookupError as error:
        raise_not_found(error)
