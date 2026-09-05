"""Declarative expected outcomes and reusable comparison conditions."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from .base import DomainModel, FrozenJsonObject, canonical_json, freeze_json


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


class Equals(DomainModel):
    """Require an observed value to equal one JSON-compatible value."""

    kind: Literal["equals"] = "equals"
    expected: Any

    @field_validator("expected", mode="before")
    @classmethod
    def freeze_expected(cls, value: Any) -> Any:
        return freeze_json(value)


class WithinTolerance(DomainModel):
    """Require a numeric observation to fall within an absolute tolerance."""

    kind: Literal["within_tolerance"] = "within_tolerance"
    expected: float = Field(allow_inf_nan=False)
    epsilon: float = Field(default=1e-6, gt=0, allow_inf_nan=False)


class WithinRange(DomainModel):
    """Require a numeric observation to fall within optional inclusive bounds."""

    kind: Literal["within_range"] = "within_range"
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bounds(self) -> "WithinRange":
        if self.minimum is None and self.maximum is None:
            raise ValueError("within_range requires minimum or maximum")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum must not exceed maximum")
        return self


class MatchesPattern(DomainModel):
    """Require a string observation to match a valid regular expression."""

    kind: Literal["matches_pattern"] = "matches_pattern"
    pattern: str

    @model_validator(mode="after")
    def validate_pattern(self) -> "MatchesPattern":
        try:
            re.compile(self.pattern)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from exc
        return self


class OneOf(DomainModel):
    """Require an observed value to equal one member of a nonempty JSON set."""

    kind: Literal["one_of"] = "one_of"
    allowed: tuple[Any, ...] = Field(min_length=1)

    @field_validator("allowed", mode="before")
    @classmethod
    def freeze_allowed(cls, value: Any) -> tuple[Any, ...]:
        return tuple(freeze_json(item) for item in value)

    @model_validator(mode="after")
    def validate_unique_values(self) -> "OneOf":
        serialized = tuple(canonical_json(item) for item in self.allowed)
        if len(set(serialized)) != len(serialized):
            raise ValueError("one_of values must be unique")
        return self


class MustBeMissing(DomainModel):
    """Require an object path or observation to be absent."""

    kind: Literal["must_be_missing"] = "must_be_missing"


class MatchesJsonSchema(DomainModel):
    """Require an observed JSON value to satisfy a JSON Schema document."""

    kind: Literal["matches_json_schema"] = "matches_json_schema"
    json_schema: FrozenJsonObject


Condition = Annotated[
    Equals
    | WithinTolerance
    | WithinRange
    | MatchesPattern
    | OneOf
    | MustBeMissing
    | MatchesJsonSchema,
    Field(discriminator="kind"),
]


class _ExpectationBase(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _require_non_blank(value, "Expectation id")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is not None:
            return _require_non_blank(value, "Expectation name")
        return value


class SkillRouteExpectation(_ExpectationBase):
    """Describe the expected Skill selected for one conversation turn."""

    kind: Literal["skill_route"] = "skill_route"
    condition: Condition


class ToolCallExpectation(_ExpectationBase):
    """Require or forbid one Tool call during a conversation turn."""

    kind: Literal["tool_call"] = "tool_call"
    tool: str
    mode: Literal["required", "forbidden"] = "required"

    @field_validator("tool")
    @classmethod
    def validate_tool(cls, value: str) -> str:
        return _require_non_blank(value, "Tool name")


class ToolArgumentExpectation(_ExpectationBase):
    """Describe an expected argument value for selected calls to one Tool."""

    kind: Literal["tool_argument"] = "tool_argument"
    tool: str
    path: str
    occurrence: Literal["first", "last", "any", "all"] = "last"
    condition: Condition

    @field_validator("tool", "path")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        return _require_non_blank(value, "Tool argument reference")


class StateExpectation(_ExpectationBase):
    """Describe an expected value in the final Agent state."""

    kind: Literal["state"] = "state"
    path: str
    condition: Condition

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _require_non_blank(value, "State path")


class OutputExpectation(_ExpectationBase):
    """Describe an expected final output or one value within it."""

    kind: Literal["output"] = "output"
    path: str | None = None
    condition: Condition

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is not None:
            return _require_non_blank(value, "Output path")
        return value


class PolicyExpectation(_ExpectationBase):
    """Require execution to comply with one externally defined business policy."""

    kind: Literal["policy"] = "policy"
    policy_id: str

    @field_validator("policy_id")
    @classmethod
    def validate_policy_id(cls, value: str) -> str:
        return _require_non_blank(value, "Policy id")


Expectation = Annotated[
    SkillRouteExpectation
    | ToolCallExpectation
    | ToolArgumentExpectation
    | StateExpectation
    | OutputExpectation
    | PolicyExpectation,
    Field(discriminator="kind"),
]
