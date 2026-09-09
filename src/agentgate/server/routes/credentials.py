"""Safe API Key management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from agentgate.application.credential_management import ApiKeyManagement
from agentgate.domain.credential import ApiKeyMetadata, ApiKeyScope
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_not_found, raise_unprocessable


router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


def _api_key_management(dependencies: ServerDependencies) -> ApiKeyManagement:
    if dependencies.api_keys is None:
        raise HTTPException(
            status_code=503,
            detail="API Key management is unavailable",
        )
    return dependencies.api_keys


class CreateApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    provider_id: str
    scope: ApiKeyScope
    api_key: SecretStr = Field(json_schema_extra={"writeOnly": True})


@router.post("", status_code=201, response_model=ApiKeyMetadata)
def create_api_key(
    request: CreateApiKeyRequest,
    dependencies: Dependencies,
) -> ApiKeyMetadata:
    try:
        management = _api_key_management(dependencies)
        return management.create_api_key(
            name=request.name,
            provider_id=request.provider_id,
            scope=request.scope,
            plaintext=request.api_key.get_secret_value(),
        )
    except ValueError as error:
        raise_unprocessable(error)


@router.get("", response_model=list[ApiKeyMetadata])
def list_api_keys(dependencies: Dependencies) -> list[ApiKeyMetadata]:
    return _api_key_management(dependencies).list_api_keys()


@router.get("/{api_key_id}", response_model=ApiKeyMetadata)
def get_api_key(
    api_key_id: str,
    dependencies: Dependencies,
) -> ApiKeyMetadata:
    try:
        return _api_key_management(dependencies).get_api_key(api_key_id)
    except LookupError as error:
        raise_not_found(error)


@router.delete("/{api_key_id}", status_code=204)
def delete_api_key(api_key_id: str, dependencies: Dependencies) -> None:
    try:
        _api_key_management(dependencies).delete_api_key(api_key_id)
    except LookupError as error:
        raise_not_found(error)


__all__ = ["router"]
