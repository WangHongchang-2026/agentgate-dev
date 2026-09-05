"""Versioned evaluator definitions composed through explicit references."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import DomainModel, FrozenJsonObject, content_sha256, require_non_blank


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "bearer_token",
    "client_secret",
    "password",
    "secret_key",
}


def _secret_path(value: Any, prefix: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key.lower().replace("-", "_") in _SECRET_KEYS:
                return path
            found = _secret_path(item, path)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _secret_path(item, f"{prefix}[{index}]")
            if found:
                return found
    return None


class EvaluatorKind(StrEnum):
    """Execution method used by an Evaluator."""

    RULE = "rule"
    LLM_JUDGE = "llm_judge"
    HYBRID = "hybrid"


class EvaluatorSeverity(StrEnum):
    """Whether an Evaluator failure may block a release gate."""

    STANDARD = "standard"
    BLOCKING = "blocking"


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
        path = _secret_path(value)
        if path:
            raise ValueError(f"EvaluatorSpec config contains credential-like field: {path}")
        return value

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if value and not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_composition_and_hash(self) -> "EvaluatorSpec":
        if self.kind == EvaluatorKind.LLM_JUDGE:
            model = self.config.get("model")
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
            (child.evaluator_id, child.evaluator_version) for child in self.children
        )
        if len(set(child_keys)) != len(child_keys):
            raise ValueError("Hybrid child Evaluator references must be unique")

        if self.kind != EvaluatorKind.HYBRID:
            if self.children or self.combination is not None:
                raise ValueError("non-Hybrid Evaluator cannot define composition")
        else:
            if len(self.children) < 2 or self.combination is None:
                raise ValueError(
                    "Hybrid Evaluator requires at least two children and a combination"
                )
            weighted = self.combination == CombinationPolicy.WEIGHTED_SCORE
            if weighted and any(child.weight is None for child in self.children):
                raise ValueError("weighted_score requires every child to have a weight")
            if not weighted and any(child.weight is not None for child in self.children):
                raise ValueError("only weighted_score children may define weights")

        expected = content_sha256(
            self.model_dump(mode="json", exclude={"content_sha256"})
        )
        if self.content_sha256 and self.content_sha256 != expected:
            raise ValueError("EvaluatorSpec content hash mismatch")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", expected)
        return self
