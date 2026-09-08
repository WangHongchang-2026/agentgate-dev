"""Immutable outputs for evidence-backed evaluation optimization."""

from __future__ import annotations

import math
import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import (
    DomainModel,
    content_sha256,
    normalize_utc,
    require_non_blank,
    require_sha256,
    utcnow,
)
from .evaluator import EvaluatorSeverity
from .result import FailureStage
from .target import TargetRef


_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


def _require_unique_text(
    values: tuple[str, ...],
    field_name: str,
) -> tuple[str, ...]:
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must not contain blank values")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicate values")
    return values


def _require_span_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if any(not _SPAN_ID_PATTERN.fullmatch(value) for value in values):
        raise ValueError("span_ids must contain lowercase OTel Span IDs")
    if len(set(values)) != len(values):
        raise ValueError("span_ids must be unique")
    return values


class FailedResultEvidence(DomainModel):
    """Stable reference and summary for one failed Evaluation Result."""

    run_id: str
    case_id: str
    result_id: str
    trace_id: str
    evaluator_id: str
    dimension: str
    metric: str
    severity: EvaluatorSeverity
    failure_stage: FailureStage
    reason: str
    span_ids: tuple[str, ...] = ()

    @field_validator(
        "run_id",
        "case_id",
        "result_id",
        "evaluator_id",
        "dimension",
        "metric",
        "reason",
    )
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"FailedResultEvidence {info.field_name}")

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, value: str) -> str:
        if not _TRACE_ID_PATTERN.fullmatch(value):
            raise ValueError("trace_id must be exactly 32 lowercase hexadecimal characters")
        return value

    @field_validator("span_ids")
    @classmethod
    def validate_span_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_span_ids(value)


class FailureCluster(DomainModel):
    """One deterministic group of failed Results with shared characteristics."""

    id: str
    category: str
    label: str
    failure_stage: FailureStage
    evaluator_id: str
    dimension: str
    metric: str
    severity: EvaluatorSeverity
    members: tuple[FailedResultEvidence, ...] = Field(min_length=1)
    representative_result_ids: tuple[str, ...] = Field(min_length=1)
    failure_count: int = Field(ge=1)
    case_count: int = Field(ge=1)
    share: float = Field(gt=0, le=1)

    @field_validator("id", "category", "label", "evaluator_id", "dimension", "metric")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"FailureCluster {info.field_name}")

    @field_validator("representative_result_ids")
    @classmethod
    def validate_representatives(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique_text(value, "representative_result_ids")

    @model_validator(mode="after")
    def validate_cluster(self) -> "FailureCluster":
        result_ids = tuple(member.result_id for member in self.members)
        if len(set(result_ids)) != len(result_ids):
            raise ValueError("FailureCluster member Result IDs must be unique")
        if self.failure_count != len(self.members):
            raise ValueError("failure_count must equal the number of cluster members")
        if self.case_count != len({member.case_id for member in self.members}):
            raise ValueError("case_count must equal the number of unique member Cases")
        if not set(self.representative_result_ids).issubset(result_ids):
            raise ValueError("representative Result IDs must belong to the cluster")
        expected = (
            self.failure_stage,
            self.evaluator_id,
            self.dimension,
            self.metric,
            self.severity,
        )
        for member in self.members:
            actual = (
                member.failure_stage,
                member.evaluator_id,
                member.dimension,
                member.metric,
                member.severity,
            )
            if actual != expected:
                raise ValueError("cluster members must match the cluster dimensions")
        return self


class ObservedRouteKind(StrEnum):
    """Observed routing outcome for one eligible Skill expectation."""

    SKILL = "skill"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


class ObservedRoute(DomainModel):
    """One selected Skill or an explicit non-Skill routing bucket."""

    kind: ObservedRouteKind
    skill_id: str | None = None

    @field_validator("skill_id")
    @classmethod
    def validate_skill_id(cls, value: str | None) -> str | None:
        return require_non_blank(value, "ObservedRoute skill_id") if value else None

    @model_validator(mode="after")
    def validate_route(self) -> "ObservedRoute":
        if self.kind is ObservedRouteKind.SKILL and self.skill_id is None:
            raise ValueError("observed Skill route requires skill_id")
        if self.kind is not ObservedRouteKind.SKILL and self.skill_id is not None:
            raise ValueError("missing or ambiguous route cannot contain skill_id")
        return self


class RoutingObservation(DomainModel):
    """One expected-versus-observed Skill decision for a Case turn."""

    case_id: str
    turn_id: str
    expectation_id: str
    result_id: str
    trace_id: str
    expected_skill_id: str
    actual_route: ObservedRoute
    span_ids: tuple[str, ...] = ()

    @field_validator(
        "case_id",
        "turn_id",
        "expectation_id",
        "result_id",
        "expected_skill_id",
    )
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"RoutingObservation {info.field_name}")

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, value: str) -> str:
        if not _TRACE_ID_PATTERN.fullmatch(value):
            raise ValueError("trace_id must be exactly 32 lowercase hexadecimal characters")
        return value

    @field_validator("span_ids")
    @classmethod
    def validate_span_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_span_ids(value)

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.case_id, self.turn_id, self.expectation_id)


class RoutingConfusionCell(DomainModel):
    """Observed routing decisions at one expected/actual matrix coordinate."""

    expected_skill_id: str
    actual_route: ObservedRoute
    observations: tuple[RoutingObservation, ...] = Field(min_length=1)
    count: int = Field(ge=1)

    @field_validator("expected_skill_id")
    @classmethod
    def validate_expected_skill_id(cls, value: str) -> str:
        return require_non_blank(value, "RoutingConfusionCell expected_skill_id")

    @model_validator(mode="after")
    def validate_cell(self) -> "RoutingConfusionCell":
        if self.count != len(self.observations):
            raise ValueError("cell count must equal its observation count")
        identities = tuple(observation.identity for observation in self.observations)
        if len(set(identities)) != len(identities):
            raise ValueError("routing observations must be unique within a cell")
        if any(
            observation.expected_skill_id != self.expected_skill_id
            or observation.actual_route != self.actual_route
            for observation in self.observations
        ):
            raise ValueError("routing observations must match their matrix cell")
        return self


class RoutingExclusion(DomainModel):
    """One routing expectation excluded from the observed matrix with a reason."""

    case_id: str
    turn_id: str
    expectation_id: str
    reason: str

    @field_validator("case_id", "turn_id", "expectation_id", "reason")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"RoutingExclusion {info.field_name}")

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.case_id, self.turn_id, self.expectation_id)


class RoutingConfusionMatrix(DomainModel):
    """Observed expected-versus-actual routing counts for one Run."""

    cells: tuple[RoutingConfusionCell, ...] = ()
    eligible_count: int = Field(ge=0)
    exclusions: tuple[RoutingExclusion, ...] = ()

    @model_validator(mode="after")
    def validate_matrix(self) -> "RoutingConfusionMatrix":
        coordinates = tuple(
            (
                cell.expected_skill_id,
                cell.actual_route.kind,
                cell.actual_route.skill_id,
            )
            for cell in self.cells
        )
        if len(set(coordinates)) != len(coordinates):
            raise ValueError("routing confusion-matrix coordinates must be unique")
        observations = tuple(
            observation
            for cell in self.cells
            for observation in cell.observations
        )
        observation_ids = tuple(observation.identity for observation in observations)
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("routing observations must appear in exactly one cell")
        if self.eligible_count != sum(cell.count for cell in self.cells):
            raise ValueError("eligible_count must equal all matrix cell counts")
        exclusion_ids = tuple(exclusion.identity for exclusion in self.exclusions)
        if len(set(exclusion_ids)) != len(exclusion_ids):
            raise ValueError("routing exclusions must be unique")
        if set(observation_ids).intersection(exclusion_ids):
            raise ValueError("routing expectations cannot be eligible and excluded")
        return self


class RootCauseHypothesis(DomainModel):
    """Evidence-backed possible cause that explicitly remains a hypothesis."""

    id: str
    category: str
    title: str
    explanation: str
    confidence: float = Field(ge=0, le=1)
    cluster_ids: tuple[str, ...] = Field(min_length=1)
    result_ids: tuple[str, ...] = Field(min_length=1)
    span_ids: tuple[str, ...] = ()
    static_finding_ids: tuple[str, ...] = ()

    @field_validator("id", "category", "title", "explanation")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"RootCauseHypothesis {info.field_name}")

    @field_validator("cluster_ids", "result_ids", "static_finding_ids")
    @classmethod
    def validate_reference_ids(
        cls, value: tuple[str, ...], info: ValidationInfo
    ) -> tuple[str, ...]:
        return _require_unique_text(value, info.field_name)

    @field_validator("span_ids")
    @classmethod
    def validate_span_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_span_ids(value)


class SuggestionPriority(StrEnum):
    """Human-review ordering for one optimization suggestion."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OptimizationSuggestion(DomainModel):
    """One evidence-backed recommendation that requires human review."""

    id: str
    target: str
    target_id: str | None = None
    priority: SuggestionPriority
    title: str
    recommendation: str
    rationale: str
    hypothesis_ids: tuple[str, ...] = Field(min_length=1)
    requires_human_review: Literal[True] = True

    @field_validator("id", "target", "title", "recommendation", "rationale")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"OptimizationSuggestion {info.field_name}")

    @field_validator("target_id")
    @classmethod
    def validate_target_id(cls, value: str | None) -> str | None:
        return require_non_blank(value, "OptimizationSuggestion target_id") if value else None

    @field_validator("hypothesis_ids")
    @classmethod
    def validate_hypothesis_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique_text(value, "hypothesis_ids")


class OptimizationReport(DomainModel):
    """Complete deterministic optimization analysis for one completed Run."""

    run_id: str
    target_ref: TargetRef
    target_content_sha256: str
    dataset_id: str
    dataset_version: int = Field(ge=1)
    dataset_content_sha256: str
    analyzer_version: str
    failed_result_count: int = Field(ge=0)
    clusters: tuple[FailureCluster, ...] = ()
    confusion_matrix: RoutingConfusionMatrix
    hypotheses: tuple[RootCauseHypothesis, ...] = ()
    suggestions: tuple[OptimizationSuggestion, ...] = ()
    created_at: datetime = Field(default_factory=utcnow)
    content_sha256: str = ""

    @field_validator("run_id", "dataset_id", "analyzer_version")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"OptimizationReport {info.field_name}")

    @field_validator(
        "target_content_sha256",
        "dataset_content_sha256",
        "content_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str, info: ValidationInfo) -> str:
        return require_sha256(value, info.field_name) if value else value

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return normalize_utc(value, "created_at")

    @model_validator(mode="after")
    def validate_report(self) -> "OptimizationReport":
        cluster_ids = tuple(cluster.id for cluster in self.clusters)
        if len(set(cluster_ids)) != len(cluster_ids):
            raise ValueError("FailureCluster IDs must be unique within a report")
        hypothesis_ids = tuple(hypothesis.id for hypothesis in self.hypotheses)
        if len(set(hypothesis_ids)) != len(hypothesis_ids):
            raise ValueError("RootCauseHypothesis IDs must be unique within a report")
        suggestion_ids = tuple(suggestion.id for suggestion in self.suggestions)
        if len(set(suggestion_ids)) != len(suggestion_ids):
            raise ValueError("OptimizationSuggestion IDs must be unique within a report")

        members = tuple(member for cluster in self.clusters for member in cluster.members)
        result_ids = tuple(member.result_id for member in members)
        if len(set(result_ids)) != len(result_ids):
            raise ValueError("failed Results must appear in exactly one cluster")
        if any(member.run_id != self.run_id for member in members):
            raise ValueError("cluster evidence must belong to the report Run")
        if self.failed_result_count == 0 and (
            self.clusters or self.hypotheses or self.suggestions
        ):
            raise ValueError("report without failed Results cannot contain optimization output")
        if self.failed_result_count != len(members):
            raise ValueError("failed_result_count must equal all clustered Results")
        if self.failed_result_count:
            for cluster in self.clusters:
                expected_share = cluster.failure_count / self.failed_result_count
                if not math.isclose(cluster.share, expected_share, abs_tol=1e-12):
                    raise ValueError("cluster share does not match report failure count")

        clusters_by_id = {cluster.id: cluster for cluster in self.clusters}
        for hypothesis in self.hypotheses:
            unknown_clusters = set(hypothesis.cluster_ids).difference(clusters_by_id)
            if unknown_clusters:
                raise ValueError("hypothesis references an unknown failure cluster")
            supported_members = tuple(
                member
                for cluster_id in hypothesis.cluster_ids
                for member in clusters_by_id[cluster_id].members
            )
            supported_results = {member.result_id for member in supported_members}
            if not set(hypothesis.result_ids).issubset(supported_results):
                raise ValueError("hypothesis references a Result outside its clusters")
            supported_spans = {
                span_id for member in supported_members for span_id in member.span_ids
            }
            if not set(hypothesis.span_ids).issubset(supported_spans):
                raise ValueError("hypothesis references a Span outside its clusters")

        known_hypotheses = set(hypothesis_ids)
        if any(
            not set(suggestion.hypothesis_ids).issubset(known_hypotheses)
            for suggestion in self.suggestions
        ):
            raise ValueError("suggestion references an unknown root-cause hypothesis")

        expected_hash = content_sha256(
            self.model_dump(mode="json", exclude={"created_at", "content_sha256"})
        )
        if self.content_sha256 and self.content_sha256 != expected_hash:
            raise ValueError("OptimizationReport content hash mismatch")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", expected_hash)
        return self


__all__ = [
    "FailedResultEvidence",
    "FailureCluster",
    "ObservedRoute",
    "ObservedRouteKind",
    "OptimizationReport",
    "OptimizationSuggestion",
    "RootCauseHypothesis",
    "RoutingConfusionCell",
    "RoutingConfusionMatrix",
    "RoutingExclusion",
    "RoutingObservation",
    "SuggestionPriority",
]
