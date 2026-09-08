from __future__ import annotations

import re

import pytest

from agentgate.evaluator.rule.json_schema import (
    JsonSchemaConfigurationError,
    json_schema_failure_reason,
    validate_json_schema,
)


def test_defaults_to_draft_2020_12_and_validates_nested_constraints() -> None:
    schema = {
        "type": "object",
        "required": ["profile"],
        "properties": {
            "profile": {
                "type": "object",
                "required": ["age"],
                "properties": {"age": {"type": "integer", "minimum": 18}},
            }
        },
    }

    assert validate_json_schema(schema) is None
    assert json_schema_failure_reason({"profile": {"age": 21}}, schema) is None
    assert json_schema_failure_reason({"profile": {"age": 17}}, schema) == (
        "JSON Schema violation at $.profile.age (minimum)"
    )


def test_accepts_explicit_draft_2020_12_and_rejects_other_drafts() -> None:
    validate_json_schema(
        {"$schema": "https://json-schema.org/draft/2020-12/schema"}
    )

    with pytest.raises(JsonSchemaConfigurationError, match="Draft 2020-12"):
        validate_json_schema(
            {"$schema": "http://json-schema.org/draft-07/schema#"}
        )


def test_rejects_malformed_schema_without_echoing_its_value() -> None:
    with pytest.raises(
        JsonSchemaConfigurationError,
        match=r"invalid Draft 2020-12 JSON Schema at \$\.type",
    ) as raised:
        validate_json_schema({"type": "private-invalid-type"})

    assert "private-invalid-type" not in str(raised.value)


def test_supports_resolved_local_defs_json_pointer() -> None:
    schema = {
        "$defs": {
            "identifier": {"type": "string", "pattern": "^[A-Z]+$"},
        },
        "$ref": "#/$defs/identifier",
    }

    assert json_schema_failure_reason("VALID", schema) is None
    assert json_schema_failure_reason("invalid", schema) == (
        "JSON Schema violation at $ (pattern)"
    )


@pytest.mark.parametrize(
    "reference",
    (
        "https://schemas.example/item.json",
        "file:///tmp/item.json",
        "item.json#/$defs/value",
        "#named-anchor",
    ),
)
def test_rejects_non_pointer_references(reference: str) -> None:
    with pytest.raises(JsonSchemaConfigurationError, match="local JSON Pointer"):
        validate_json_schema({"$ref": reference})


def test_rejects_unresolved_local_reference() -> None:
    with pytest.raises(JsonSchemaConfigurationError, match="does not resolve"):
        validate_json_schema({"$ref": "#/$defs/missing"})


@pytest.mark.parametrize("keyword", ("$dynamicRef", "$recursiveRef"))
def test_rejects_dynamic_reference_keywords(keyword: str) -> None:
    with pytest.raises(JsonSchemaConfigurationError, match=re.escape(keyword)):
        validate_json_schema({keyword: "#/$defs/value", "$defs": {"value": {}}})


def test_reason_is_deterministic_bounded_and_does_not_echo_actual_values() -> None:
    long_key = "private_" + "x" * 500
    schema = {
        "type": "object",
        "properties": {
            "b": {"type": "integer"},
            "a": {"type": "integer"},
            long_key: {"type": "integer"},
        },
    }
    actual = {"a": "first-secret", "b": "second-secret", long_key: "third-secret"}

    reason = json_schema_failure_reason(actual, schema)

    assert reason == "JSON Schema violation at $.a (type)"
    assert all(secret not in reason for secret in actual.values())
    assert len(
        json_schema_failure_reason({long_key: "third-secret"}, schema)
    ) <= 400


def test_structured_mode_never_parses_json_looking_strings() -> None:
    reason = json_schema_failure_reason('{"answer": "ok"}', {"type": "object"})

    assert reason == "JSON Schema violation at $ (type)"


def test_distinguishes_json_null_and_leaves_format_checking_disabled() -> None:
    assert json_schema_failure_reason(None, {"type": "null"}) is None
    assert json_schema_failure_reason(
        "not-an-email",
        {"type": "string", "format": "email"},
    ) is None
