"""Metric aggregation plans and calculated summaries."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import DomainModel, require_non_blank


MetricLevel: TypeAlias = Literal["overall", "kind", "dimension", "metric"]


class MetricPlan(DomainModel):
    """Exact metric algorithm selected for one Run."""

    id: str = "p1-equal-mean"
    version: str = "1"

    @field_validator("id", "version")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"MetricPlan {info.field_name}")


class MetricSummary(DomainModel):
    """Calculated score and outcome counts for one aggregation key."""

    key: str
    level: MetricLevel
    score: float | None = Field(default=None, ge=0, le=1)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    reviewed: int = Field(default=0, ge=0)
    not_applicable: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    applicable: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return require_non_blank(value, "MetricSummary key")

    @model_validator(mode="after")
    def validate_summary(self) -> "MetricSummary":
        counted = (
            self.passed
            + self.failed
            + self.reviewed
            + self.not_applicable
            + self.errors
        )
        if self.total != counted:
            raise ValueError("total must equal all outcome counts")
        if self.applicable != self.passed + self.failed + self.reviewed:
            raise ValueError("applicable must equal passed + failed + reviewed")
        if (self.score is None) != (self.applicable == 0):
            raise ValueError("score must exist exactly when applicable results exist")
        if (self.level == "overall") != (self.key == "overall"):
            raise ValueError("overall level and key must be used together")
        return self
