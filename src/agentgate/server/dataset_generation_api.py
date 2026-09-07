"""HTTP transport for automatic Dataset generation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from agentgate.application.dataset_generation import DatasetGenerationError, DatasetGenerationService
from agentgate.application.target_catalog import TargetCatalog
from agentgate.case.generation.models import (
    CategoryCounts,
    DifficultyCounts,
    GenerationRequest,
    ReferenceSource,
    ReviewedGeneratedCase,
    TurnCounts,
    TurnMode,
)
from agentgate.domain import Case, TargetRef, TargetType
from agentgate.integrations.model_providers import GenerationProviderError
from agentgate.integrations.model_providers import RuntimeCredentialStore
from agentgate.storage.base import DatasetDraftConflictError, DatasetIdempotencyConflictError

_EXPECTED_GENERATION_ERRORS = (
    DatasetGenerationError,
    GenerationProviderError,
    DatasetDraftConflictError,
    DatasetIdempotencyConflictError,
    ValueError,
)


class HttpModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateCandidatesRequest(HttpModel):
    draft_id: str
    draft_content_sha256: str
    target_ref: TargetRef
    count: int
    reference_source: ReferenceSource | None = None
    reference_case_ids: tuple[str, ...] = ()
    turn_mode: TurnMode = TurnMode.SINGLE
    turn_counts: TurnCounts | None = None
    max_turns_per_case: int = 3
    category_counts: CategoryCounts
    difficulty_counts: DifficultyCounts
    instructions: str = ""
    model_profile_id: str = "dataset-generator-default"


class ValidateGeneratedCandidateRequest(HttpModel):
    draft_id: str
    draft_content_sha256: str
    target_ref: TargetRef
    target_descriptor_sha256: str
    recipe_version: str
    acceptance_token: str = Field(min_length=20, max_length=4096)
    candidate_id: str
    slot_index: int = Field(ge=0, le=19)
    case: Case


class AcceptGeneratedCasesRequest(HttpModel):
    draft_id: str
    draft_content_sha256: str
    target_ref: TargetRef
    target_descriptor_sha256: str
    recipe_version: str
    acceptance_token: str = Field(min_length=20, max_length=4096)
    candidates: tuple[ReviewedGeneratedCase, ...] = Field(min_length=1, max_length=20)


class ConfigureModelCredentialRequest(HttpModel):
    api_key: SecretStr


def _detail(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    issues: tuple[Any, ...] = (),
    request_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if issues:
        payload["issues"] = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in issues
        ]
    if request_id:
        payload["request_id"] = request_id
    return payload


def _raise_generation_error(exc: Exception) -> None:
    if isinstance(exc, GenerationProviderError):
        status = 504 if exc.code == "provider_timeout" else (
            429 if exc.code in {"provider_rate_limited", "generation_capacity_exceeded"} else 502
        )
        raise HTTPException(status_code=status, detail=_detail(
            exc.code, str(exc), retryable=exc.retryable, request_id=exc.request_id
        )) from exc
    if isinstance(exc, (DatasetDraftConflictError, DatasetIdempotencyConflictError)):
        code = "idempotency_conflict" if isinstance(
            exc, DatasetIdempotencyConflictError
        ) else "draft_conflict"
        raise HTTPException(status_code=409, detail=_detail(code, str(exc))) from exc
    if isinstance(exc, DatasetGenerationError):
        if exc.code in {"draft_conflict", "descriptor_conflict", "recipe_conflict"}:
            status = 409
        elif exc.code in {"draft_not_found", "unknown_model_profile", "unknown_reference_case"}:
            status = 404
        elif exc.code == "provider_credential_unavailable":
            status = 502
        else:
            status = 422
        raise HTTPException(
            status_code=status,
            detail=_detail(exc.code, str(exc), issues=exc.issues),
        ) from exc
    raise HTTPException(
        status_code=404 if "unknown target" in str(exc) else 422,
        detail=_detail("invalid_request", str(exc)),
    ) from exc


def create_dataset_generation_router(
    service: DatasetGenerationService,
    targets: TargetCatalog,
    credential_store: RuntimeCredentialStore | None = None,
    credential_validator: Callable[[Any, str], str | None] | None = None,
) -> APIRouter:
    api = APIRouter(prefix="/api")

    @api.get("/targets")
    def list_targets(target_type: TargetType | None = Query(default=None)):
        return targets.list_targets(target_type)

    @api.get("/targets/{platform_id}/{target_type}/{external_target_id}/versions")
    def list_target_versions(
        platform_id: str,
        target_type: TargetType,
        external_target_id: str,
    ):
        versions = targets.list_versions(platform_id, target_type, external_target_id)
        if not versions:
            raise HTTPException(
                status_code=404,
                detail=_detail("target_not_found", "未找到评测对象"),
            )
        return [{
            "ref": item.ref,
            "display_name": item.display_name,
            "description": item.description,
            "descriptor_sha256": item.descriptor_sha256,
            "reproducibility_limited": item.reproducibility_limited,
        } for item in versions]

    @api.get("/dataset-generation/model-profiles")
    def list_model_profiles():
        return service.list_model_profiles()

    @api.put("/dataset-generation/model-profiles/{profile_id}/credential")
    def configure_model_credential(
        profile_id: str,
        request: ConfigureModelCredentialRequest,
    ):
        if credential_store is None or credential_validator is None:
            raise HTTPException(
                status_code=501,
                detail=_detail("credential_configuration_unavailable", "当前服务不支持页面配置凭据"),
            )
        api_key = request.api_key.get_secret_value().strip()
        if len(api_key) < 8 or len(api_key) > 4096:
            raise HTTPException(
                status_code=422,
                detail=_detail("invalid_credential", "API Key 格式无效"),
            )
        try:
            profile = service.model_profile(profile_id)
            request_id = credential_validator(profile, api_key)
            credential_store.set(profile.credential_ref, api_key)
            return {
                "profile_id": profile.id,
                "available": True,
                "storage": "process_memory",
                "validation_request_id": request_id,
            }
        except _EXPECTED_GENERATION_ERRORS as exc:
            _raise_generation_error(exc)

    @api.delete("/dataset-generation/model-profiles/{profile_id}/credential")
    def delete_model_credential(profile_id: str):
        if credential_store is None:
            raise HTTPException(
                status_code=501,
                detail=_detail("credential_configuration_unavailable", "当前服务不支持页面配置凭据"),
            )
        try:
            profile = service.model_profile(profile_id)
            credential_store.delete(profile.credential_ref)
            availability = getattr(service.model, "credential_available", lambda _profile: True)
            return {
                "profile_id": profile.id,
                "available": bool(availability(profile)),
                "storage": "environment" if availability(profile) else "none",
            }
        except _EXPECTED_GENERATION_ERRORS as exc:
            _raise_generation_error(exc)

    @api.post("/datasets/{dataset_id}/drafts/generate-candidates")
    def generate_candidates(dataset_id: str, request: GenerateCandidatesRequest):
        try:
            internal = GenerationRequest.model_validate(request.model_dump(mode="json"))
            return service.generate(dataset_id, internal)
        except _EXPECTED_GENERATION_ERRORS as exc:
            _raise_generation_error(exc)

    @api.post("/datasets/{dataset_id}/drafts/generated-candidates/validate")
    def validate_candidate(dataset_id: str, request: ValidateGeneratedCandidateRequest):
        try:
            return service.validate_candidate(
                dataset_id=dataset_id,
                draft_id=request.draft_id,
                draft_hash=request.draft_content_sha256,
                target_ref=request.target_ref,
                target_descriptor_sha256=request.target_descriptor_sha256,
                recipe_version=request.recipe_version,
                acceptance_token=request.acceptance_token,
                candidate_id=request.candidate_id,
                slot_index=request.slot_index,
                case=request.case,
            )
        except _EXPECTED_GENERATION_ERRORS as exc:
            _raise_generation_error(exc)

    @api.post("/datasets/{dataset_id}/drafts/cases/batch")
    def accept_candidates(
        dataset_id: str,
        request: AcceptGeneratedCasesRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ):
        try:
            return service.accept_cases(
                dataset_id=dataset_id,
                draft_id=request.draft_id,
                draft_hash=request.draft_content_sha256,
                target_ref=request.target_ref,
                target_descriptor_sha256=request.target_descriptor_sha256,
                recipe_version=request.recipe_version,
                acceptance_token=request.acceptance_token,
                candidates=request.candidates,
                idempotency_key=idempotency_key,
            )
        except _EXPECTED_GENERATION_ERRORS as exc:
            _raise_generation_error(exc)

    return api
