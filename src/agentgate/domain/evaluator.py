"""Persisted evaluator definitions and judge snapshots."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import DomainModel, FrozenJsonObject


class Kind(StrEnum):
    RULE = "rule"
    LLM_JUDGE = "llm_judge"
    HYBRID = "hybrid"


class Dimension(StrEnum):
    ROUTING = "routing"
    TOOL_USE = "tool_use"
    STATE = "state"
    ANSWER = "answer"
    SAFETY = "safety"
    EFFICIENCY = "efficiency"


class Severity(StrEnum):
    STANDARD = "standard"
    BLOCKING = "blocking"


class MethodRef(DomainModel):
    operator: str
    operator_version: str
    condition_kind: str | None = None


class PromptSnapshot(DomainModel):
    id: str
    version: str
    content: str
    sha256: str


class RubricSnapshot(DomainModel):
    id: str
    version: str
    content: FrozenJsonObject
    sha256: str


class JudgeConfig(DomainModel):
    provider: str
    model: str
    prompt: PromptSnapshot
    rubric: RubricSnapshot
    temperature: float = 0
    seed: int | None = None
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)


class JudgeEvidence(DomainModel):
    requested_model: str
    resolved_model: str | None = None
    prompt_sha256: str
    rubric_sha256: str
    raw_response: str
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None


class ChildRef(DomainModel):
    evaluator_id: str
    version: str
    weight: float = Field(gt=0)


class EvaluatorBase(DomainModel):
    id: str
    name: str
    version: str = "1"
    dimension: Dimension
    metric: str
    severity: Severity = Severity.STANDARD


class RuleEvaluatorSpec(EvaluatorBase):
    kind: Literal[Kind.RULE] = Kind.RULE
    evaluator_type: str
    operator: str | None = None
    operator_version: str | None = None
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)

    @model_validator(mode="after")
    def operator_fields_match(self) -> "RuleEvaluatorSpec":
        if (self.operator is None) != (self.operator_version is None):
            raise ValueError("operator and operator_version must both be present or absent")
        return self


class LlmJudgeEvaluatorSpec(EvaluatorBase):
    kind: Literal[Kind.LLM_JUDGE] = Kind.LLM_JUDGE
    evaluator_type: str
    judge: JudgeConfig
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)


class HybridEvaluatorSpec(EvaluatorBase):
    kind: Literal[Kind.HYBRID] = Kind.HYBRID
    evaluator_type: str
    children: tuple[ChildRef, ...]
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)


EvaluatorSpec = Annotated[
    RuleEvaluatorSpec | LlmJudgeEvaluatorSpec | HybridEvaluatorSpec,
    Field(discriminator="kind"),
]
