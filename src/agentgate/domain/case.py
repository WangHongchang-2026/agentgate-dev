"""Versioned evaluation Datasets, Cases, and conversation turns."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from .base import DomainModel, FrozenJsonObject, content_sha256
from .expectation import Expectation


def utcnow() -> datetime:
    return datetime.now(UTC)


class CaseCategory(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"


class CaseDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class DatasetPurpose(StrEnum):
    STANDARD = "standard"
    REGRESSION = "regression"


class DatasetVersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class CaseProvenance(DomainModel):
    source_type: Literal["run_result"] = "run_result"
    source_run_id: str
    source_dataset_id: str
    source_dataset_version: int
    source_case_id: str
    captured_at: datetime
    reason: str = ""


class CaseTurn(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    input: FrozenJsonObject
    expected_skill: str | None = None
    expectations: tuple[Expectation, ...] = ()
    required_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    policy_rules: tuple[str, ...] = ()
    notes: str = ""


class Case(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    turns: tuple[CaseTurn, ...] = Field(min_length=1)
    initial_state: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    category: CaseCategory = CaseCategory.POSITIVE
    difficulty: CaseDifficulty = CaseDifficulty.MEDIUM
    tags: tuple[str, ...] = ()
    notes: str = ""
    provenance: CaseProvenance | None = None

    @property
    def input(self) -> FrozenJsonObject:
        """Convenience for single-turn targets and display code."""
        return self.turns[-1].input


class Dataset(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    purpose: DatasetPurpose = DatasetPurpose.STANDARD
    archived: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DatasetVersion(DomainModel):
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

    @model_validator(mode="after")
    def validate_version_and_hash(self) -> "DatasetVersion":
        if self.status == DatasetVersionStatus.PUBLISHED:
            if self.version is None or self.published_at is None:
                raise ValueError("published DatasetVersion requires version and published_at")
        elif self.version is not None or self.published_at is not None:
            raise ValueError("draft DatasetVersion cannot have version or published_at")
        cases = []
        for case in self.cases:
            serialized = case.model_dump(mode="json")
            if serialized["provenance"] is None:
                del serialized["provenance"]
            cases.append(serialized)
        payload = {
            "dataset_id": self.dataset_id,
            "cases": cases,
            "notes": self.notes,
        }
        expected = content_sha256(payload)
        if self.content_sha256 and self.content_sha256 != expected:
            raise ValueError("DatasetVersion content hash mismatch")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", expected)
        return self
