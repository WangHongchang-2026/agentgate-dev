"""Versioned evaluator definitions composed through explicit references."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import (
    DomainModel,
    FrozenJsonObject,
    content_sha256,
    find_credential_path,
    normalize_utc,
    require_non_blank,
    require_sha256,
    utcnow,
)


class EvaluatorKind(StrEnum):
    """Execution method used by an Evaluator."""

    RULE = "rule"
    LLM_JUDGE = "llm_judge"
    HYBRID = "hybrid"


class EvaluatorSeverity(StrEnum):
    """Whether an Evaluator failure may block a release gate."""

    STANDARD = "standard"
    BLOCKING = "blocking"


class EvaluatorSource(StrEnum):
    """Ownership boundary that controls catalog mutation."""

    BUILTIN = "builtin"
    USER = "user"


class CombinationPolicy(StrEnum):
    """How a Hybrid Evaluator combines its child Results."""

    ALL = "all"
    ANY = "any"
    WEIGHTED_SCORE = "weighted_score"


class EvaluatorRef(DomainModel):
    """Exact reference to one child Evaluator version."""

    evaluator_id: str
    evaluator_version: str
    weight: float | None = Field(default=None, gt=0)

    @field_validator("evaluator_id", "evaluator_version")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"EvaluatorRef {info.field_name}")


class Evaluator(DomainModel):
    """Stable catalog identity and editable metadata for one Evaluator."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    source: EvaluatorSource = EvaluatorSource.USER
    enabled: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("id", "name")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"Evaluator {info.field_name}")

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime, info: ValidationInfo) -> datetime:
        return normalize_utc(value, info.field_name)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "Evaluator":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.source == EvaluatorSource.BUILTIN and not self.enabled:
            raise ValueError("built-in Evaluator must be enabled")
        return self


class EvaluatorDraft(DomainModel):
    """Structurally complete unpublished configuration for one user Evaluator."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    evaluator_id: str
    based_on_version: str | None = None
    kind: EvaluatorKind = EvaluatorKind.RULE
    dimension: str
    metric: str
    severity: EvaluatorSeverity = EvaluatorSeverity.STANDARD
    implementation_id: str
    implementation_version: str = "1"
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    children: tuple[EvaluatorRef, ...] = ()
    combination: CombinationPolicy | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator(
        "id",
        "evaluator_id",
        "dimension",
        "metric",
        "implementation_id",
        "implementation_version",
    )
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"EvaluatorDraft {info.field_name}")

    @field_validator("based_on_version")
    @classmethod
    def validate_base_version(cls, value: str | None) -> str | None:
        if value is not None:
            return require_non_blank(value, "EvaluatorDraft based_on_version")
        return None

    @field_validator("config")
    @classmethod
    def reject_plaintext_credentials(cls, value: FrozenJsonObject) -> FrozenJsonObject:
        return _reject_plaintext_credentials(value, "EvaluatorDraft")

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime, info: ValidationInfo) -> datetime:
        return normalize_utc(value, info.field_name)

    @model_validator(mode="after")
    def validate_definition(self) -> "EvaluatorDraft":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        _validate_definition(
            self.kind,
            self.config,
            self.children,
            self.combination,
        )
        return self


class EvaluatorSpec(DomainModel):
    """Immutable definition of one directly executable or composed Evaluator."""

    id: str
    name: str
    version: str = "1"
    kind: EvaluatorKind = EvaluatorKind.RULE
    dimension: str
    metric: str
    severity: EvaluatorSeverity = EvaluatorSeverity.STANDARD
    implementation_id: str
    implementation_version: str = "1"
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    children: tuple[EvaluatorRef, ...] = ()
    combination: CombinationPolicy | None = None
    content_sha256: str = ""

    @field_validator(
        "id",
        "name",
        "version",
        "dimension",
        "metric",
        "implementation_id",
        "implementation_version",
    )
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"EvaluatorSpec {info.field_name}")

    @field_validator("config")
    @classmethod
    def reject_plaintext_credentials(cls, value: FrozenJsonObject) -> FrozenJsonObject:
        return _reject_plaintext_credentials(value, "EvaluatorSpec")

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        return require_sha256(value, "content_sha256") if value else value

    @model_validator(mode="after")
    def validate_composition_and_hash(self) -> "EvaluatorSpec":
        _validate_definition(
            self.kind,
            self.config,
            self.children,
            self.combination,
        )

        expected = content_sha256(
            self.model_dump(mode="json", exclude={"content_sha256"})
        )
        if self.content_sha256 and self.content_sha256 != expected:
            raise ValueError("EvaluatorSpec content hash mismatch")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", expected)
        return self


def _reject_plaintext_credentials(
    config: FrozenJsonObject,
    owner: str,
) -> FrozenJsonObject:
    path = find_credential_path(config)
    if path:
        raise ValueError(f"{owner} config contains credential-like field: {path}")
    return config


def _validate_definition(
    kind: EvaluatorKind,
    config: FrozenJsonObject,
    children: tuple[EvaluatorRef, ...],
    combination: CombinationPolicy | None,
) -> None:
    if kind == EvaluatorKind.LLM_JUDGE:
        model = config.get("model")
        if not isinstance(model, Mapping):
            raise ValueError("LLM Judge config requires a model object")
        for field_name in ("provider_id", "model_id"):
            value = model.get(field_name)
            if not isinstance(value, str):
                raise ValueError(
                    f"LLM Judge config model.{field_name} must be a string"
                )
            require_non_blank(value, f"LLM Judge config model.{field_name}")
        credential_ref = model.get("credential_ref")
        if credential_ref is not None:
            if not isinstance(credential_ref, str):
                raise ValueError(
                    "LLM Judge config model.credential_ref must be a string"
                )
            require_non_blank(
                credential_ref, "LLM Judge config model.credential_ref"
            )

    child_keys = tuple(
        (child.evaluator_id, child.evaluator_version) for child in children
    )
    if len(set(child_keys)) != len(child_keys):
        raise ValueError("Hybrid child Evaluator references must be unique")

    if kind != EvaluatorKind.HYBRID:
        if children or combination is not None:
            raise ValueError("non-Hybrid Evaluator cannot define composition")
        return

    if len(children) < 2 or combination is None:
        raise ValueError(
            "Hybrid Evaluator requires at least two children and a combination"
        )
    weighted = combination == CombinationPolicy.WEIGHTED_SCORE
    if weighted and any(child.weight is None for child in children):
        raise ValueError("weighted_score requires every child to have a weight")
    if not weighted and any(child.weight is not None for child in children):
        raise ValueError("only weighted_score children may define weights")
