"""Persisted domain records produced by static Skill analysis."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import DomainModel, FrozenJsonObject, content_sha256
from .target import TargetRef


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _normalize_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


class SkillAnalysisStatus(StrEnum):
    """Completion state of a static Skill-analysis report."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class FindingSeverity(StrEnum):
    """Potential impact of a static-analysis finding."""

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    BLOCKING = "blocking"


class ReviewDecision(StrEnum):
    """Human disposition recorded for one finding."""

    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    ACCEPTED_RISK = "accepted_risk"
    DEFERRED = "deferred"


class SkillAnalysisFinding(DomainModel):
    """One reviewable issue detected in an Agent or Skill definition."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    check_id: str
    category: str
    severity: FindingSeverity
    confidence: float = Field(ge=0, le=1)
    skill_ids: tuple[str, ...] = ()
    reason: str
    evidence: tuple[FrozenJsonObject, ...]
    suggestions: tuple[str, ...] = ()

    @field_validator("id", "check_id", "category", "reason")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_blank(value, f"SkillAnalysisFinding {info.field_name}")

    @field_validator("skill_ids", "suggestions")
    @classmethod
    def validate_text_collection(
        cls, value: tuple[str, ...], info: ValidationInfo
    ) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError(f"{info.field_name} must not contain blank values")
        if len(set(value)) != len(value):
            raise ValueError(f"{info.field_name} must not contain duplicate values")
        return value

    @field_validator("evidence")
    @classmethod
    def require_evidence(
        cls, value: tuple[FrozenJsonObject, ...]
    ) -> tuple[FrozenJsonObject, ...]:
        if not value:
            raise ValueError("SkillAnalysisFinding requires evidence")
        return value


class SkillAnalysisReport(DomainModel):
    """Immutable output of one static analysis of an exact Target descriptor."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    target_ref: TargetRef
    target_descriptor_sha256: str
    analyzer_version: str
    analyzer_config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    status: SkillAnalysisStatus
    findings: tuple[SkillAnalysisFinding, ...] = ()
    risk_matrix: tuple[FrozenJsonObject, ...] = ()
    errors: tuple[FrozenJsonObject, ...] = ()
    created_at: datetime = Field(default_factory=utcnow)
    content_sha256: str = ""

    @field_validator("id", "analyzer_version")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_blank(value, f"SkillAnalysisReport {info.field_name}")

    @field_validator("target_descriptor_sha256", "content_sha256")
    @classmethod
    def validate_hash(cls, value: str, info: ValidationInfo) -> str:
        if value and not _SHA256_PATTERN.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 digest")
        return value

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "created_at")

    @model_validator(mode="after")
    def validate_report(self) -> "SkillAnalysisReport":
        finding_ids = tuple(finding.id for finding in self.findings)
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("Finding ids must be unique within a SkillAnalysisReport")

        if self.status == SkillAnalysisStatus.COMPLETED and self.errors:
            raise ValueError("completed SkillAnalysisReport cannot contain errors")
        if self.status == SkillAnalysisStatus.PARTIAL and not self.errors:
            raise ValueError("partial SkillAnalysisReport requires at least one error")
        if self.status == SkillAnalysisStatus.FAILED:
            if not self.errors:
                raise ValueError("failed SkillAnalysisReport requires at least one error")
            if self.findings or self.risk_matrix:
                raise ValueError("failed SkillAnalysisReport cannot contain analysis output")

        expected_hash = content_sha256(
            self.model_dump(
                mode="json", exclude={"id", "created_at", "content_sha256"}
            )
        )
        if self.content_sha256 and self.content_sha256 != expected_hash:
            raise ValueError("SkillAnalysisReport content hash mismatch")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", expected_hash)
        return self


class SkillAnalysisReview(DomainModel):
    """Human decision recorded separately from an immutable analysis report."""

    finding_id: str
    decision: ReviewDecision
    reviewer_id: str
    comment: str | None = None
    reviewed_at: datetime = Field(default_factory=utcnow)

    @field_validator("finding_id", "reviewer_id")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_blank(value, f"SkillAnalysisReview {info.field_name}")

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("SkillAnalysisReview comment must not be blank")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def normalize_reviewed_at(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "reviewed_at")
