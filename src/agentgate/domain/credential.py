"""Safe API Key identity and metadata."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import DomainModel, normalize_utc, require_non_blank, utcnow


class ApiKeyScope(StrEnum):
    """Capacity and ownership scope assigned to an API Key."""

    SHARED = "shared"
    PRIVATE = "private"


class ApiKeyMetadata(DomainModel):
    """Secret-free identity returned by API Key management workflows."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    provider_id: str
    scope: ApiKeyScope
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("id", "name", "provider_id")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"ApiKeyMetadata {info.field_name}")

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(
        cls, value: datetime, info: ValidationInfo
    ) -> datetime:
        return normalize_utc(value, f"ApiKeyMetadata {info.field_name}")

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> "ApiKeyMetadata":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        return self


__all__ = ["ApiKeyMetadata", "ApiKeyScope"]
