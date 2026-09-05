import pytest
from pydantic import TypeAdapter, ValidationError

from agentgate.domain import (
    Equals,
    Expectation,
    MatchesPattern,
    OneOf,
    PolicyExpectation,
    SkillRouteExpectation,
    ToolArgumentExpectation,
    ToolCallExpectation,
    WithinRange,
    WithinTolerance,
)


def test_condition_values_are_recursively_immutable():
    source = {"nested": [{"value": 1}]}
    condition = Equals(expected=source)
    source["nested"][0]["value"] = 2
    assert condition.expected["nested"][0]["value"] == 1
    with pytest.raises(TypeError):
        condition.expected["nested"][0]["value"] = 3


def test_condition_construction_rejects_invalid_rules():
    with pytest.raises(ValidationError):
        MatchesPattern(pattern="[")
    with pytest.raises(ValidationError):
        WithinRange()
    with pytest.raises(ValidationError):
        WithinTolerance(expected=float("inf"))
    with pytest.raises(ValidationError):
        OneOf(allowed=())
    with pytest.raises(ValidationError, match="must be unique"):
        OneOf(allowed=({"value": 1}, {"value": 1}))

    assert OneOf(allowed=({"value": 1},)).allowed[0]["value"] == 1


def test_expectation_union_parses_each_observation_subject():
    adapter = TypeAdapter(Expectation)

    route = adapter.validate_python(
        {
            "kind": "skill_route",
            "id": "route",
            "condition": {"kind": "equals", "expected": "loan"},
        }
    )
    tool = adapter.validate_python(
        {"kind": "tool_call", "id": "tool", "tool": "credit", "mode": "forbidden"}
    )
    policy = adapter.validate_python(
        {"kind": "policy", "id": "policy", "policy_id": "P1"}
    )

    assert isinstance(route, SkillRouteExpectation)
    assert isinstance(tool, ToolCallExpectation)
    assert isinstance(policy, PolicyExpectation)


def test_expectation_references_cannot_be_blank():
    with pytest.raises(ValidationError):
        ToolCallExpectation(tool=" ")
    with pytest.raises(ValidationError):
        ToolArgumentExpectation(
            tool="credit", path=" ", condition=Equals(expected=1)
        )
    with pytest.raises(ValidationError):
        PolicyExpectation(policy_id=" ")
