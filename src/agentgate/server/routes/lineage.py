"""Read-only Evaluation Run lineage endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from agentgate.application import LineageGraph
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_conflict, raise_not_found


router = APIRouter(prefix="/api", tags=["lineage"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


@router.get("/runs/{run_id}/lineage")
def run_lineage(run_id: str, dependencies: Dependencies) -> LineageGraph:
    try:
        return dependencies.lineage.get_run_lineage(run_id)
    except LookupError as error:
        if str(error).startswith("unknown EvaluationRun"):
            raise_not_found(error)
        raise_conflict(error)
    except ValueError as error:
        raise_conflict(error)
