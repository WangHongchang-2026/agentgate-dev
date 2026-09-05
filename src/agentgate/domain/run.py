"""Evaluation Run lifecycle and immutable execution manifest."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import DomainModel, content_sha256, normalize_utc, require_non_blank, utcnow
from .dataset import DatasetVersion, DatasetVersionStatus
from .evaluator import EvaluatorSpec
from .gate import ReleaseGateSpec
from .metric import MetricPlan
from .target import TargetSnapshot


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RunStatus(StrEnum):
    """Lifecycle state of an Evaluation Run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunManifest(DomainModel):
    """Exact immutable inputs and effective configuration for one Evaluation Run."""

    dataset: DatasetVersion
    target: TargetSnapshot
    evaluator_specs: tuple[EvaluatorSpec, ...] = Field(min_length=1)
    primary_evaluator_ids: tuple[str, ...] = Field(min_length=1)
    metric_plan: MetricPlan
    gate_spec: ReleaseGateSpec
    timeout_seconds: float = Field(default=300, gt=0)
    max_retries: int = Field(default=0, ge=0)
    max_parallel_cases: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utcnow)
    manifest_sha256: str = ""

    @field_validator("primary_evaluator_ids")
    @classmethod
    def validate_primary_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("primary_evaluator_ids must not contain blank values")
        if len(set(value)) != len(value):
            raise ValueError("primary_evaluator_ids must be unique")
        return value

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return normalize_utc(value, "RunManifest created_at")

    @field_validator("manifest_sha256")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        if value and not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("manifest_sha256 must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> "RunManifest":
        if self.dataset.status != DatasetVersionStatus.PUBLISHED:
            raise ValueError("RunManifest requires a published DatasetVersion")

        evaluator_ids = tuple(item.id for item in self.evaluator_specs)
        if len(set(evaluator_ids)) != len(evaluator_ids):
            raise ValueError("Evaluator ids must be unique within a RunManifest")
        unknown_primary = set(self.primary_evaluator_ids).difference(evaluator_ids)
        if unknown_primary:
            raise ValueError(
                "primary_evaluator_ids reference unknown Evaluators: "
                + ", ".join(sorted(unknown_primary))
            )

        expected = content_sha256({
            "dataset": {
                "id": self.dataset.id,
                "dataset_id": self.dataset.dataset_id,
                "version": self.dataset.version,
                "content_sha256": self.dataset.content_sha256,
            },
            "target": {
                "ref": self.target.ref.model_dump(mode="json"),
                "content_sha256": self.target.content_sha256,
            },
            "evaluators": [
                {
                    "id": item.id,
                    "version": item.version,
                    "content_sha256": item.content_sha256,
                }
                for item in self.evaluator_specs
            ],
            "primary_evaluator_ids": self.primary_evaluator_ids,
            "metric_plan": self.metric_plan.model_dump(mode="json"),
            "gate_spec": self.gate_spec.model_dump(mode="json"),
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "max_parallel_cases": self.max_parallel_cases,
        })
        if self.manifest_sha256 and self.manifest_sha256 != expected:
            raise ValueError("RunManifest content hash mismatch")
        if not self.manifest_sha256:
            object.__setattr__(self, "manifest_sha256", expected)
        return self


class EvaluationRun(DomainModel):
    """Lifecycle record for one complete Dataset evaluation."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    manifest: RunManifest
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return require_non_blank(value, "EvaluationRun id")

    @field_validator("created_at", "started_at", "completed_at")
    @classmethod
    def normalize_timestamps(
        cls, value: datetime | None, info: ValidationInfo
    ) -> datetime | None:
        return (
            normalize_utc(value, f"EvaluationRun {info.field_name}")
            if value is not None
            else None
        )

    @field_validator("error")
    @classmethod
    def validate_error(cls, value: str | None) -> str | None:
        if value is not None:
            return require_non_blank(value, "EvaluationRun error")
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "EvaluationRun":
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at must not precede created_at")
        if self.completed_at is not None:
            earliest = self.started_at or self.created_at
            if self.completed_at < earliest:
                raise ValueError("completed_at must not precede Run activity")

        if self.status == RunStatus.PENDING:
            if self.started_at is not None or self.completed_at is not None or self.error:
                raise ValueError("pending EvaluationRun cannot contain execution outcome")
        elif self.status == RunStatus.RUNNING:
            if self.started_at is None or self.completed_at is not None or self.error:
                raise ValueError("running EvaluationRun requires only started_at")
        elif self.status == RunStatus.COMPLETED:
            if self.started_at is None or self.completed_at is None or self.error:
                raise ValueError(
                    "completed EvaluationRun requires timestamps and no error"
                )
        elif self.status == RunStatus.FAILED:
            if self.completed_at is None or self.error is None:
                raise ValueError("failed EvaluationRun requires completed_at and error")
        elif self.status == RunStatus.CANCELLED:
            if self.completed_at is None or self.error is not None:
                raise ValueError("cancelled EvaluationRun requires completed_at and no error")
        return self


_ALLOWED_TRANSITIONS = {
    RunStatus.PENDING: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.RUNNING: {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED},
}


def transition_run(
    run: EvaluationRun,
    new_status: RunStatus,
    occurred_at: datetime | None = None,
    error: str | None = None,
) -> EvaluationRun:
    """Return a new EvaluationRun after one legal lifecycle transition."""

    if new_status not in _ALLOWED_TRANSITIONS.get(run.status, set()):
        raise ValueError(f"illegal Run transition: {run.status} -> {new_status}")
    timestamp = normalize_utc(occurred_at or utcnow(), "transition occurred_at")
    if timestamp < (run.started_at or run.created_at):
        raise ValueError("transition occurred_at must not precede Run activity")

    updates: dict[str, object] = {"status": new_status, "error": None}
    if new_status == RunStatus.RUNNING:
        if error is not None:
            raise ValueError("running transition cannot contain an error")
        updates["started_at"] = timestamp
    else:
        updates["completed_at"] = timestamp
        if new_status == RunStatus.FAILED:
            if error is None or not error.strip():
                raise ValueError("failed transition requires an error")
            updates["error"] = error
        elif error is not None:
            raise ValueError("only failed transition may contain an error")

    return EvaluationRun.model_validate(
        {**run.model_dump(mode="json"), **updates}
    )
