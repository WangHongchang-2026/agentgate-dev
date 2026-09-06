"""Evaluation Run submission and listing endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agentgate.domain import EvaluationRun
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_unprocessable


router = APIRouter(prefix="/api", tags=["runs"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


class LaunchRequest(BaseModel):
    version: str
    dataset_id: str
    dataset_version: int = Field(ge=1)
    evaluator_ids: list[str] | None = None


@router.get("/runs")
def list_runs(dependencies: Dependencies) -> list[EvaluationRun]:
    return dependencies.results.list_runs()


@router.post("/evaluations", status_code=201)
def launch_evaluation(
    request: LaunchRequest, dependencies: Dependencies
) -> EvaluationRun:
    try:
        return dependencies.execute_demo_run(
            request.version,
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            evaluator_ids=request.evaluator_ids,
        )
    except ValueError as error:
        raise_unprocessable(error)
