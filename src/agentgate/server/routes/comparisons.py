"""Evaluation Run comparison endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from agentgate.result import EvaluationComparison
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_conflict, raise_not_found


router = APIRouter(prefix="/api", tags=["comparisons"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


@router.get("/run-comparisons")
def compare_runs(
    baseline_run_id: str,
    candidate_run_id: str,
    dependencies: Dependencies,
) -> EvaluationComparison:
    try:
        return dependencies.results.compare_runs(
            baseline_run_id,
            candidate_run_id,
        )
    except LookupError as error:
        raise_not_found(error)
    except ValueError as error:
        raise_conflict(error)
