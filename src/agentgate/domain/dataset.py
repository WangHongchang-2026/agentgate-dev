"""Dataset catalog and immutable Dataset-version domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import DomainModel, content_sha256, require_non_blank, utcnow
from .case import Case


def _normalize_utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


class DatasetVersionStatus(StrEnum):
    """Lifecycle state of a Dataset version record."""

    DRAFT = "draft"
    PUBLISHED = "published"


class Dataset(DomainModel):
    """Stable catalog identity and editable display metadata for a Dataset."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    archived: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("id", "name")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"Dataset {info.field_name}")

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime, info: ValidationInfo) -> datetime:
        normalized = _normalize_utc(value, info.field_name)
        assert normalized is not None
        return normalized

    @model_validator(mode="after")
    def validate_timestamps(self) -> "Dataset":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        return self


class DatasetVersion(DomainModel):
    """Ordered, content-addressed snapshot of Cases belonging to one Dataset."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    dataset_id: str
    dataset_name: str = ""
    dataset_description: str = ""
    version: int | None = Field(default=None, ge=1)
    status: DatasetVersionStatus = DatasetVersionStatus.DRAFT
    based_on_version: int | None = Field(default=None, ge=1)
    cases: tuple[Case, ...] = ()
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    published_at: datetime | None = None
    content_sha256: str = ""

    @field_validator("id", "dataset_id")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"DatasetVersion {info.field_name}")

    @field_validator("created_at", "updated_at", "published_at")
    @classmethod
    def normalize_timestamps(
        cls, value: datetime | None, info: ValidationInfo
    ) -> datetime | None:
        return _normalize_utc(value, info.field_name)

    @model_validator(mode="after")
    def validate_version(self) -> "DatasetVersion":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")

        if self.status == DatasetVersionStatus.DRAFT:
            if self.version is not None or self.published_at is not None:
                raise ValueError("draft DatasetVersion cannot be numbered or published")
        else:
            if self.version is None or self.published_at is None:
                raise ValueError(
                    "published DatasetVersion requires version and published_at"
                )
            if not self.cases:
                raise ValueError("published DatasetVersion requires at least one Case")
            if self.published_at < self.created_at:
                raise ValueError("published_at must not precede created_at")
            if self.published_at > self.updated_at:
                raise ValueError("published_at must not follow updated_at")
            if (
                self.based_on_version is not None
                and self.based_on_version >= self.version
            ):
                raise ValueError("based_on_version must precede version")

        case_ids = tuple(case.id for case in self.cases)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("Case ids must be unique within a DatasetVersion")

        expected_hash = content_sha256(
            {
                "dataset_id": self.dataset_id,
                "cases": [case.model_dump(mode="json") for case in self.cases],
                "notes": self.notes,
            }
        )
        if self.content_sha256 and self.content_sha256 != expected_hash:
            raise ValueError("DatasetVersion content hash mismatch")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", expected_hash)
        return self
