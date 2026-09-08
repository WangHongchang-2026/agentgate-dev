"""Read-only lineage endpoints."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from agentgate.application import LineageGraph
from agentgate.domain import TargetRef, TargetType
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_conflict, raise_not_found


router = APIRouter(prefix="/api", tags=["lineage"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]
Version = Annotated[int, Path(ge=1)]
Limit = Annotated[int, Query(ge=1, le=200)]
ContentHash = Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")]


@router.get("/runs/{run_id}/lineage")
def run_lineage(run_id: str, dependencies: Dependencies) -> LineageGraph:
    return _read_lineage(lambda: dependencies.lineage.get_run_lineage(run_id))


@router.get("/datasets/{dataset_id}/versions/{version}/lineage")
def dataset_lineage(
    dataset_id: str,
    version: Version,
    dependencies: Dependencies,
    limit: Limit = 50,
) -> LineageGraph:
    return _read_lineage(
        lambda: dependencies.lineage.get_dataset_lineage(
            dataset_id, version, limit
        )
    )


@router.get("/datasets/{dataset_id}/versions/{version}/cases/{case_id}/lineage")
def case_lineage(
    dataset_id: str,
    version: Version,
    case_id: str,
    dependencies: Dependencies,
    limit: Limit = 50,
) -> LineageGraph:
    return _read_lineage(
        lambda: dependencies.lineage.get_case_lineage(
            dataset_id, version, case_id, limit
        )
    )


@router.get(
    "/targets/{source_id}/{target_type}/{target_id}/versions/{version}/lineage"
)
def target_lineage(
    source_id: str,
    target_type: TargetType,
    target_id: str,
    version: str,
    dependencies: Dependencies,
    limit: Limit = 50,
    content_sha256: ContentHash = None,
) -> LineageGraph:
    ref = TargetRef(
        source_id=source_id,
        target_type=target_type,
        external_target_id=target_id,
        external_version_id=version,
    )
    return _read_lineage(
        lambda: dependencies.lineage.get_target_lineage(
            ref,
            content_hash=content_sha256,
            limit=limit,
        )
    )


@router.get("/skills/{source_id}/{skill_id}/versions/{version}/lineage")
def skill_lineage(
    source_id: str,
    skill_id: str,
    version: str,
    dependencies: Dependencies,
    limit: Limit = 50,
    content_sha256: ContentHash = None,
) -> LineageGraph:
    return _read_lineage(
        lambda: dependencies.lineage.get_skill_lineage(
            source_id,
            skill_id,
            version,
            content_hash=content_sha256,
            limit=limit,
        )
    )


@router.get("/evaluators/{evaluator_id}/versions/{version}/lineage")
def evaluator_lineage(
    evaluator_id: str,
    version: str,
    dependencies: Dependencies,
    limit: Limit = 50,
    content_sha256: ContentHash = None,
) -> LineageGraph:
    return _read_lineage(
        lambda: dependencies.lineage.get_evaluator_lineage(
            evaluator_id,
            version,
            content_hash=content_sha256,
            limit=limit,
        )
    )


def _read_lineage(load: Callable[[], LineageGraph]) -> LineageGraph:
    try:
        return load()
    except LookupError as error:
        if str(error).startswith("unknown TargetDescriptor"):
            raise_conflict(error)
        raise_not_found(error)
    except ValueError as error:
        raise_conflict(error)
