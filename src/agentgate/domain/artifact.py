"""References and metadata for files produced during Agent execution."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, ValidationInfo, field_validator

from .base import DomainModel, FrozenJsonObject, require_non_blank


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class ArtifactProducer(StrEnum):
    """Execution component that produced an Artifact."""

    AGENT = "agent"
    TOOL = "tool"
    HARNESS = "harness"


class Artifact(DomainModel):
    """Immutable metadata and storage reference for one produced file."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    case_id: str
    trace_id: str | None = None
    producer: ArtifactProducer
    producer_name: str | None = None
    artifact_type: str
    filename: str
    media_type: str
    storage_uri: str
    sha256: str
    size_bytes: int = Field(ge=0)
    created_at: datetime = Field(default_factory=utcnow)
    metadata: FrozenJsonObject = Field(default_factory=FrozenJsonObject)

    @field_validator(
        "id",
        "run_id",
        "case_id",
        "artifact_type",
        "filename",
        "media_type",
        "storage_uri",
    )
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"Artifact {info.field_name}")

    @field_validator("trace_id", "producer_name")
    @classmethod
    def validate_optional_text(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        if value is not None:
            return require_non_blank(value, f"Artifact {info.field_name}")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("Artifact sha256 must be a lowercase SHA-256 digest")
        return value

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Artifact created_at must be timezone-aware")
        return value.astimezone(UTC)
