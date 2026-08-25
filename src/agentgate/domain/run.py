"""Run state and immutable execution snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, model_validator

from .base import DomainModel, FrozenJsonObject, content_sha256
from .case import DatasetVersion
from .evaluation import EvaluatorSpec
from .gate import GateSpec
from .metric import MetricPlan


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TargetSnapshot(DomainModel):
    name: str
    version: str
    provider: str
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)


class RunSnapshot(DomainModel):
    dataset: DatasetVersion
    target: TargetSnapshot
    evaluator_specs: tuple[EvaluatorSpec, ...]
    primary_evaluator_ids: tuple[str, ...]
    metric_plan: MetricPlan
    gate_spec: GateSpec
    selected_case_ids: tuple[str, ...] | None = None
    created_at: datetime = Field(default_factory=utcnow)
    snapshot_sha256: str = ""

    @model_validator(mode="after")
    def set_or_verify_hash(self) -> "RunSnapshot":
        payload = self.model_dump(mode="json", exclude={"snapshot_sha256"})
        # Keep hashes produced before selected-case execution was introduced readable.
        # A real selection remains part of the immutable execution snapshot.
        if payload["selected_case_ids"] is None:
            payload.pop("selected_case_ids")
        # Keep hashes produced before regression Case provenance was introduced readable.
        # Non-null provenance remains part of every new regression Run snapshot hash.
        for case in payload["dataset"]["cases"]:
            if case.get("provenance") is None:
                case.pop("provenance", None)
        expected = content_sha256(payload)
        if self.snapshot_sha256 and self.snapshot_sha256 != expected:
            raise ValueError("RunSnapshot content hash mismatch")
        if not self.snapshot_sha256:
            object.__setattr__(self, "snapshot_sha256", expected)
        return self

    @property
    def evaluators(self) -> tuple[EvaluatorSpec, ...]:
        return self.evaluator_specs


class Run(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: RunStatus = RunStatus.PENDING
    snapshot: RunSnapshot
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    parent_run_id: str | None = None
    root_run_id: str | None = None
    rerun_case_id: str | None = None
