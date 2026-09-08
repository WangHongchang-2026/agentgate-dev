import pytest

from agentgate.domain import (
    Equals,
    MatchesJsonSchema,
    MatchesPattern,
    MustBeMissing,
    OneOf,
    WithinRange,
    WithinTolerance,
)
from agentgate.evaluator.rule.json_schema import JsonSchemaConfigurationError
from agentgate.evaluator.rule.observations import MISSING
from agentgate.evaluator.rule.operators import (
    OperatorOutcome,
    UnknownOperator,
    contains_all,
    contains_none,
    equals,
    is_one_of,
    matches_pattern,
    matches_json_schema,
    must_be_missing,
    resolve_condition_operator,
    resolve_operator,
    within_range,
    within_tolerance,
)


def test_operator_outcome_requires_boolean_and_bounded_nonblank_reason() -> None:
    with pytest.raises(TypeError, match="must be a boolean"):
        OperatorOutcome(passed=1, reason="reason")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not be blank"):
        OperatorOutcome(passed=True, reason=" ")
    with pytest.raises(ValueError, match="must not exceed"):
        OperatorOutcome(passed=True, reason="x" * 501)


def test_equals_distinguishes_missing_from_json_null() -> None:
    condition = Equals(expected=None)

    assert equals(None, condition).passed
    assert not equals(MISSING, condition).passed
    assert not equals("value", condition).passed


def test_numeric_operators_are_inclusive_and_reject_booleans() -> None:
    tolerance = WithinTolerance(expected=0.3, epsilon=1e-6)
    bounded = WithinRange(minimum=1, maximum=5)

    assert within_tolerance(0.1 + 0.2, tolerance).passed
    assert not within_tolerance(True, tolerance).passed
    assert within_range(1, bounded).passed
    assert within_range(5, bounded).passed
    assert not within_range(True, bounded).passed
    assert not within_range(6, bounded).passed


def test_pattern_membership_and_missing_operators() -> None:
    assert matches_pattern("loan-123", MatchesPattern(pattern=r"loan-\d+")).passed
    assert not matches_pattern(123, MatchesPattern(pattern=r"\d+")).passed
    assert is_one_of("review", OneOf(allowed=("review", "reject"))).passed
    assert not is_one_of(MISSING, OneOf(allowed=(None,))).passed
    assert must_be_missing(MISSING, MustBeMissing()).passed
    assert not must_be_missing(None, MustBeMissing()).passed


def test_collection_operators_preserve_expected_order_and_bound_reasons() -> None:
    missing = contains_all(("present",), ("second", "first"))
    found = contains_none(("second", "first"), ("first", "second"))

    assert not missing.passed and missing.reason.endswith("second, first")
    assert not found.passed and found.reason.endswith("first, second")
    many = tuple(f"required-{index:03d}-with-a-long-name" for index in range(100))
    assert len(contains_all((), many).reason) <= 500


@pytest.mark.parametrize("value", ["text", ("valid", 1)])
def test_collection_operators_reject_malformed_collections(value) -> None:
    with pytest.raises(TypeError, match="collection of strings|only strings"):
        contains_all(value, ("required",))


def test_resolves_exact_operator_versions_without_registration() -> None:
    method, implementation = resolve_condition_operator(Equals(expected="approved"))

    assert method.implementation_id == "equals"
    assert method.implementation_version == "1"
    assert implementation("approved", Equals(expected="approved")).passed
    assert resolve_operator("contains_all", "1") is contains_all
    with pytest.raises(UnknownOperator, match="equals@2"):
        resolve_operator("equals", "2")


def test_json_schema_condition_resolves_with_exact_provenance_and_behavior() -> None:
    condition = MatchesJsonSchema(json_schema={"type": "object"})

    method, implementation = resolve_condition_operator(condition)

    assert method.implementation_id == "matches_json_schema"
    assert method.implementation_version == "1"
    assert implementation({"answer": "ok"}, condition) == OperatorOutcome(
        passed=True,
        reason="value matches JSON Schema",
    )
    assert implementation("not-an-object", condition) == OperatorOutcome(
        passed=False,
        reason="JSON Schema violation at $ (type)",
    )
    assert implementation(MISSING, condition) == OperatorOutcome(
        passed=False,
        reason="JSON value is missing",
    )
    assert resolve_operator("matches_json_schema", "1") is matches_json_schema


def test_json_schema_operator_propagates_configuration_errors() -> None:
    condition = MatchesJsonSchema(json_schema={"type": "private-invalid-type"})

    with pytest.raises(JsonSchemaConfigurationError, match="invalid Draft 2020-12"):
        matches_json_schema({}, condition)
