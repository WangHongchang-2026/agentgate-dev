"""Evaluator Catalog identity, draft, and publication endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agentgate.application import (
    BuiltinEvaluatorMutation,
    EvaluatorCatalogConflict,
    EvaluatorDraftNotFound,
    EvaluatorNotFound,
    EvaluatorVersionNotFound,
)
from agentgate.domain import (
    CombinationPolicy,
    Evaluator,
    EvaluatorDraft,
    EvaluatorKind,
    EvaluatorRef,
    EvaluatorSeverity,
    EvaluatorSource,
    EvaluatorSpec,
)
from agentgate.evaluator.models import EvaluatorError
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_conflict, raise_not_found, raise_unprocessable


router = APIRouter(prefix="/api/evaluators", tags=["evaluators"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftDefinitionRequest(_RequestModel):
    kind: EvaluatorKind = EvaluatorKind.RULE
    dimension: str
    metric: str
    severity: EvaluatorSeverity = EvaluatorSeverity.STANDARD
    implementation_id: str
    implementation_version: str = "1"
    config: dict[str, Any] = Field(default_factory=dict)
    children: tuple[EvaluatorRef, ...] = ()
    combination: CombinationPolicy | None = None


class CreateEvaluatorRequest(_RequestModel):
    name: str
    description: str = ""
    draft: DraftDefinitionRequest


class UpdateEvaluatorRequest(_RequestModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None


class CreateDraftRequest(_RequestModel):
    based_on_version: str | None = None


class EvaluatorSummary(BaseModel):
    id: str
    name: str
    description: str
    source: EvaluatorSource
    enabled: bool
    created_at: datetime
    updated_at: datetime
    latest_version: str | None
    kind: EvaluatorKind | None
    dimension: str | None
    metric: str | None
    severity: EvaluatorSeverity | None
    implementation_id: str | None
    implementation_version: str | None
    has_draft: bool


class EvaluatorDetail(BaseModel):
    evaluator: Evaluator
    latest: EvaluatorSpec | None
    draft: EvaluatorDraft | None


class CreatedEvaluator(BaseModel):
    evaluator: Evaluator
    draft: EvaluatorDraft


def _raise_catalog_error(error: Exception) -> NoReturn:
    if isinstance(
        error,
        (EvaluatorNotFound, EvaluatorDraftNotFound, EvaluatorVersionNotFound),
    ):
        raise_not_found(error)
    if isinstance(error, (EvaluatorCatalogConflict, BuiltinEvaluatorMutation)):
        raise_conflict(error)
    raise_unprocessable(error)


def _draft_or_none(
    evaluator: Evaluator,
    dependencies: ServerDependencies,
) -> EvaluatorDraft | None:
    if evaluator.source == EvaluatorSource.BUILTIN:
        return None
    try:
        return dependencies.evaluators.get_draft(evaluator.id)
    except EvaluatorDraftNotFound:
        return None


def _detail(
    evaluator: Evaluator,
    dependencies: ServerDependencies,
) -> EvaluatorDetail:
    versions = dependencies.evaluators.list_versions(evaluator.id)
    return EvaluatorDetail(
        evaluator=evaluator,
        latest=versions[0] if versions else None,
        draft=_draft_or_none(evaluator, dependencies),
    )


def _summary(detail: EvaluatorDetail) -> EvaluatorSummary:
    definition = detail.latest or detail.draft
    return EvaluatorSummary(
        **detail.evaluator.model_dump(),
        latest_version=detail.latest.version if detail.latest else None,
        kind=definition.kind if definition else None,
        dimension=definition.dimension if definition else None,
        metric=definition.metric if definition else None,
        severity=definition.severity if definition else None,
        implementation_id=definition.implementation_id if definition else None,
        implementation_version=(
            definition.implementation_version if definition else None
        ),
        has_draft=detail.draft is not None,
    )


@router.get("")
def list_evaluators(
    dependencies: Dependencies,
    include_disabled: bool = False,
) -> list[EvaluatorSummary]:
    try:
        return [
            _summary(_detail(evaluator, dependencies))
            for evaluator in dependencies.evaluators.list_evaluators(
                include_disabled=include_disabled
            )
        ]
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.post("", status_code=201)
def create_evaluator(
    request: CreateEvaluatorRequest,
    dependencies: Dependencies,
) -> CreatedEvaluator:
    try:
        evaluator, draft = dependencies.evaluators.create_evaluator(
            request.name,
            request.description,
            **request.draft.model_dump(),
        )
        return CreatedEvaluator(evaluator=evaluator, draft=draft)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.get("/{evaluator_id}")
def evaluator_detail(
    evaluator_id: str,
    dependencies: Dependencies,
) -> EvaluatorDetail:
    try:
        return _detail(
            dependencies.evaluators.get_evaluator(evaluator_id),
            dependencies,
        )
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.patch("/{evaluator_id}")
def update_evaluator(
    evaluator_id: str,
    request: UpdateEvaluatorRequest,
    dependencies: Dependencies,
) -> Evaluator:
    provided = request.model_fields_set
    if not provided:
        raise HTTPException(
            status_code=422,
            detail="Evaluator update must contain at least one field",
        )
    if any(getattr(request, field_name) is None for field_name in provided):
        raise HTTPException(
            status_code=422,
            detail="Evaluator update fields cannot be null",
        )
    try:
        return dependencies.evaluators.update_evaluator(
            evaluator_id,
            **request.model_dump(exclude_unset=True),
        )
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.delete("/{evaluator_id}", status_code=204)
def delete_evaluator(evaluator_id: str, dependencies: Dependencies) -> None:
    try:
        dependencies.evaluators.delete_evaluator(evaluator_id)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.get("/{evaluator_id}/versions")
def list_versions(
    evaluator_id: str,
    dependencies: Dependencies,
) -> list[EvaluatorSpec]:
    try:
        return list(dependencies.evaluators.list_versions(evaluator_id))
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.get("/{evaluator_id}/versions/{version}")
def evaluator_version(
    evaluator_id: str,
    version: str,
    dependencies: Dependencies,
) -> EvaluatorSpec:
    try:
        return dependencies.evaluators.get_version(evaluator_id, version)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.get("/{evaluator_id}/drafts/current")
def current_draft(
    evaluator_id: str,
    dependencies: Dependencies,
) -> EvaluatorDraft:
    try:
        return dependencies.evaluators.get_draft(evaluator_id)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.post("/{evaluator_id}/drafts", status_code=201)
def create_draft(
    evaluator_id: str,
    request: CreateDraftRequest,
    dependencies: Dependencies,
) -> EvaluatorDraft:
    try:
        return dependencies.evaluators.create_draft(
            evaluator_id,
            request.based_on_version,
        )
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.put("/{evaluator_id}/drafts/current")
def replace_draft(
    evaluator_id: str,
    request: DraftDefinitionRequest,
    dependencies: Dependencies,
) -> EvaluatorDraft:
    try:
        return dependencies.evaluators.replace_draft(
            evaluator_id,
            **request.model_dump(),
        )
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.delete("/{evaluator_id}/drafts/current", status_code=204)
def discard_draft(evaluator_id: str, dependencies: Dependencies) -> None:
    try:
        dependencies.evaluators.discard_draft(evaluator_id)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.post("/{evaluator_id}/drafts/publish")
def publish_draft(
    evaluator_id: str,
    dependencies: Dependencies,
) -> EvaluatorSpec:
    try:
        return dependencies.evaluators.publish_draft(evaluator_id)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)
