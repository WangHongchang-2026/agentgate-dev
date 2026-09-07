"""Runtime DTOs for case generation; persisted Case models remain in domain/."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentgate.domain import (
    Case,
    CaseCategory,
    CaseDifficulty,
    Condition,
    DomainModel,
    FrozenJsonObject,
    TargetRef,
)


class GenerationDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnMode(StrEnum):
    SINGLE = "single"
    MULTI = "multi"
    MIXED = "mixed"


class CategoryCounts(GenerationDto):
    positive: int = Field(default=0, ge=0)
    negative: int = Field(default=0, ge=0)
    boundary: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.positive + self.negative + self.boundary


class DifficultyCounts(GenerationDto):
    easy: int = Field(default=0, ge=0)
    medium: int = Field(default=0, ge=0)
    hard: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.easy + self.medium + self.hard


class TurnCounts(GenerationDto):
    single: int = Field(default=0, ge=0)
    multi: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.single + self.multi


class GenerationSlot(GenerationDto):
    index: int = Field(ge=0)
    category: CaseCategory
    difficulty: CaseDifficulty
    turn_mode: Literal["single", "multi"]


class ReferenceSource(GenerationDto):
    dataset_id: str
    version: int = Field(ge=1)


class GenerationRequest(GenerationDto):
    draft_id: str
    draft_content_sha256: str
    target_ref: TargetRef
    count: int = Field(ge=1, le=20)
    reference_source: ReferenceSource | None = None
    reference_case_ids: tuple[str, ...] = ()
    turn_mode: TurnMode = TurnMode.SINGLE
    turn_counts: TurnCounts | None = None
    max_turns_per_case: int = Field(default=3, ge=2, le=5)
    category_counts: CategoryCounts
    difficulty_counts: DifficultyCounts
    instructions: str = Field(default="", max_length=4000)
    model_profile_id: str = "dataset-generator-default"

    @model_validator(mode="after")
    def validate_counts(self) -> GenerationRequest:
        if self.category_counts.total != self.count:
            raise ValueError("category_counts must sum to count")
        if self.difficulty_counts.total != self.count:
            raise ValueError("difficulty_counts must sum to count")
        if self.turn_mode == TurnMode.MIXED:
            if self.turn_counts is None or self.turn_counts.total != self.count:
                raise ValueError("mixed turn_counts must sum to count")
            if self.turn_counts.single == 0 or self.turn_counts.multi == 0:
                raise ValueError("mixed generation requires both single and multi cases")
        elif self.turn_counts is not None:
            expected = (
                TurnCounts(single=self.count)
                if self.turn_mode == TurnMode.SINGLE
                else TurnCounts(multi=self.count)
            )
            if self.turn_counts != expected:
                raise ValueError("turn_counts conflicts with turn_mode")
        if self.reference_source is None and self.reference_case_ids:
            raise ValueError("reference_case_ids require reference_source")
        if len(self.reference_case_ids) > 20:
            raise ValueError("at most 20 reference Case IDs are allowed")
        return self


class GeneratedStateExpectation(GenerationDto):
    kind: Literal["state"] = "state"
    path: str = Field(max_length=500)
    condition: Condition
    name: str | None = Field(default=None, max_length=200)


class GeneratedToolArgumentExpectation(GenerationDto):
    kind: Literal["tool_argument"] = "tool_argument"
    tool: str = Field(max_length=200)
    path: str = Field(max_length=500)
    occurrence: Literal["first", "last", "any", "all"] = "last"
    condition: Condition
    name: str | None = Field(default=None, max_length=200)


class GeneratedOutputExpectation(GenerationDto):
    kind: Literal["output"] = "output"
    path: str | None = Field(default=None, max_length=500)
    condition: Condition
    name: str | None = Field(default=None, max_length=200)


GeneratedExpectation = Annotated[
    GeneratedStateExpectation | GeneratedToolArgumentExpectation | GeneratedOutputExpectation,
    Field(discriminator="kind"),
]


class GeneratedTurnDraft(GenerationDto):
    input: dict[str, Any] = Field(
        min_length=1,
        description=(
            "Direct business input for this turn. Do not wrap it in an AnyValue-style "
            "object such as {type: 'object', value: {...}}."
        )
    )
    expected_skill: str | None = Field(default=None, max_length=200)
    expectations: tuple[GeneratedExpectation, ...] = Field(default=(), max_length=50)
    required_tools: tuple[str, ...] = Field(default=(), max_length=50)
    forbidden_tools: tuple[str, ...] = Field(default=(), max_length=50)
    policy_rules: tuple[str, ...] = Field(default=(), max_length=50)
    notes: str = Field(default="", max_length=2000)


class GeneratedCaseDraft(GenerationDto):
    name: str = Field(min_length=1, max_length=200)
    turns: tuple[GeneratedTurnDraft, ...] = Field(min_length=1, max_length=5)
    initial_state: dict[str, Any] = Field(default_factory=dict)
    category: CaseCategory = CaseCategory.POSITIVE
    difficulty: CaseDifficulty = CaseDifficulty.MEDIUM
    tags: tuple[str, ...] = Field(default=(), max_length=50)
    notes: str = Field(default="", max_length=4000)


class GeneratedBatch(GenerationDto):
    cases: tuple[GeneratedCaseDraft, ...] = Field(max_length=20)


class GeneratedToolCallBlueprint(GenerationDto):
    tool: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    occurrence: Literal["first", "last", "any", "all"] = "last"


class GeneratedTurnBlueprint(GenerationDto):
    input: dict[str, Any] = Field(
        min_length=1,
        description="Direct business input; never wrap it in an AnyValue-style object."
    )
    expected_skill: str | None = Field(default=None, max_length=200)
    required_tool_calls: tuple[GeneratedToolCallBlueprint, ...] = Field(
        default=(), max_length=20
    )
    forbidden_tools: tuple[str, ...] = Field(default=(), max_length=50)
    output_contains: tuple[str, ...] = Field(default=(), max_length=10)
    notes: str = Field(default="", max_length=1000)


class GeneratedCaseBlueprint(GenerationDto):
    # The provider schema requires this field and binds it to one deterministic
    # generation-plan slot. Keeping it optional in the runtime DTO lets older
    # saved fixtures and non-provider callers receive a precise service-level
    # error instead of failing the entire response during parsing.
    slot_index: int | None = Field(default=None, ge=0, le=19)
    name: str = Field(min_length=1, max_length=200)
    turns: tuple[GeneratedTurnBlueprint, ...] = Field(min_length=1, max_length=5)
    category: CaseCategory
    difficulty: CaseDifficulty
    tags: tuple[str, ...] = Field(default=(), max_length=20)
    notes: str = Field(default="", max_length=2000)


class GeneratedBlueprintBatch(GenerationDto):
    cases: tuple[GeneratedCaseBlueprint, ...] = Field(max_length=20)


class CandidateIssue(DomainModel):
    path: str
    code: str
    message: str


class GeneratedCandidate(DomainModel):
    candidate_id: str
    slot_index: int | None = Field(default=None, ge=0, le=19)
    review_status: Literal["pending"] = "pending"
    case: Case | None = None
    issues: tuple[CandidateIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return self.case is not None and not self.issues


class ReviewedGeneratedCase(DomainModel):
    """A reviewed Case bound to the signed generation-plan slot it came from."""

    slot_index: int = Field(ge=0, le=19)
    case: Case


class GenerationModelProfile(DomainModel):
    id: str
    display_name: str
    provider: str
    model: str
    base_url: str
    credential_ref: str
    timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    temperature: float = Field(default=0.4, ge=0, le=2)
    max_concurrent_requests: int = Field(default=2, ge=1, le=20)

    def public_dict(self, available: bool) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "provider": self.provider,
            "model": self.model,
            "available": available,
        }


class ModelGenerationRequest(DomainModel):
    system_prompt: str
    user_payload: FrozenJsonObject
    response_schema: FrozenJsonObject
    profile: GenerationModelProfile


class ModelGenerationResponse(DomainModel):
    content: str
    request_id: str | None = None
    response_model: str | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)


class GenerationResult(DomainModel):
    requested_count: int
    generated_count: int
    valid_count: int
    invalid_count: int
    candidates: tuple[GeneratedCandidate, ...]
    batch_issues: tuple[CandidateIssue, ...] = ()
    target_ref: TargetRef
    target_descriptor_sha256: str
    recipe_version: str
    provider: str
    model_profile_id: str
    requested_model: str
    response_model: str | None = None
    provider_request_id: str | None = None
    acceptance_token: str
    redacted_count: int = Field(default=0, ge=0)
    draft_id: str
    draft_content_sha256: str


class CandidateValidation(DomainModel):
    candidate: GeneratedCandidate
    target_descriptor_sha256: str
